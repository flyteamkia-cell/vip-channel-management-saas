"""The chat flow, decided here rather than in the webhook handler (§33).

The handler parses an update and sends whatever this returns. Every choice —
which message, which buttons, whether to run onboarding — is made in this
service, so the flow can be tested by feeding it updates and reading replies,
with no Telegram anywhere near it.

The flow matches what the channel owner described: the user picks a market,
receives *that tenant's own* referral link, registers at the exchange through
it, and sends their UID back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import TelegramUser
from app.adapters.persistence.repositories import (
    ReferralProgramConfigRepository,
    TelegramChannelRepository,
    TelegramUserRepository,
)
from app.domain import messages
from app.domain.enums import Market, ProviderType
from app.domain.uid import is_valid_bitunix_uid, normalize_uid
from app.services.referral_onboarding import (
    OnboardingOutcome,
    OnboardingResult,
    ReferralOnboardingService,
)

MARKET_CALLBACK_PREFIX = "market:"

MARKET_LABELS = {
    Market.CRYPTO: "کریپتو",
    Market.FOREX: "فارکس",
}


@dataclass(frozen=True)
class IncomingUpdate:
    """The handful of fields the flow actually uses.

    Parsed at the edge so this service never sees a raw Telegram payload; an
    API change lands in the handler, not in the business flow.
    """

    chat_id: int
    user_id: int
    text: str | None = None
    callback_data: str | None = None
    username: str | None = None
    first_name: str | None = None


@dataclass
class Reply:
    text: str
    reply_markup: dict | None = None


@dataclass
class ConversationResult:
    replies: list[Reply] = field(default_factory=list)


class BotConversation:
    def __init__(
        self,
        session: AsyncSession,
        onboarding: ReferralOnboardingService,
        provider_type: ProviderType = ProviderType.BITUNIX,
    ) -> None:
        self._session = session
        self._onboarding = onboarding
        self._provider_type = provider_type
        self._users = TelegramUserRepository(session)
        self._configs = ReferralProgramConfigRepository(session)
        self._channels = TelegramChannelRepository(session)

    async def handle(self, tenant_id: UUID, update: IncomingUpdate) -> ConversationResult:
        if update.callback_data and update.callback_data.startswith(MARKET_CALLBACK_PREFIX):
            raw = update.callback_data[len(MARKET_CALLBACK_PREFIX) :]
            try:
                market = Market(raw)
            except ValueError:
                return ConversationResult([Reply(messages.NOT_CONFIGURED)])
            return await self._offer_referral_link(tenant_id, update, market)

        text = (update.text or "").strip()

        if text.startswith("/start"):
            return await self._start(tenant_id, update)

        if text and normalize_uid(text).isdigit():
            return await self._handle_uid(tenant_id, update, text)

        return ConversationResult([Reply(messages.ASK_FOR_UID)])

    async def _available_markets(self, tenant_id: UUID) -> list[Market]:
        """A market is offered only when it is completely set up.

        Showing a button for a market with no channel hands the user a dead end
        two steps later. §29's spirit is that misconfiguration surfaces to the
        operator, not to the customer's members.
        """
        configs = await self._configs.list_all(tenant_id)
        channels = await self._channels.list_all(tenant_id)
        with_channel = {c.market for c in channels if c.is_active}
        ready = {
            c.market
            for c in configs
            if c.is_active and c.provider_type == self._provider_type
        } & with_channel
        return sorted(ready)

    async def _ensure_user(self, tenant_id: UUID, update: IncomingUpdate) -> TelegramUser:
        user = await self._users.get_by_telegram_id(tenant_id, update.user_id)
        if user is None:
            user = await self._users.save(
                tenant_id,
                TelegramUser(
                    tenant_id=tenant_id,
                    telegram_user_id=update.user_id,
                    username=update.username,
                    first_name=update.first_name,
                ),
            )
        return user

    async def _start(self, tenant_id: UUID, update: IncomingUpdate) -> ConversationResult:
        markets = await self._available_markets(tenant_id)
        if not markets:
            return ConversationResult([Reply(messages.NOT_CONFIGURED)])

        if len(markets) == 1:
            # One market: a button offering no choice is just an extra tap.
            return await self._offer_referral_link(tenant_id, update, markets[0])

        buttons = [
            [{"text": MARKET_LABELS[m], "callback_data": f"{MARKET_CALLBACK_PREFIX}{m.value}"}]
            for m in markets
        ]
        return ConversationResult(
            [Reply(messages.CHOOSE_MARKET, reply_markup={"inline_keyboard": buttons})]
        )

    async def _offer_referral_link(
        self, tenant_id: UUID, update: IncomingUpdate, market: Market
    ) -> ConversationResult:
        config = await self._configs.get_for(tenant_id, self._provider_type, market)
        if config is None or not config.is_active:
            return ConversationResult([Reply(messages.NOT_CONFIGURED)])

        user = await self._ensure_user(tenant_id, update)
        # Remembered in the database, not in memory: a redeploy between the
        # button and the UID must not lose the choice.
        user.pending_market = market

        return ConversationResult(
            [
                Reply(
                    messages.WELCOME.format(
                        name=update.first_name or "",
                        referral_link=config.referral_link,
                    )
                )
            ]
        )

    async def _handle_uid(
        self, tenant_id: UUID, update: IncomingUpdate, raw_text: str
    ) -> ConversationResult:
        uid = normalize_uid(raw_text)
        if not is_valid_bitunix_uid(uid):
            return ConversationResult([Reply(messages.INVALID_UID)])

        user = await self._users.get_by_telegram_id(tenant_id, update.user_id)
        market = user.pending_market if user else None
        if market is None:
            available = await self._available_markets(tenant_id)
            if len(available) != 1:
                # A UID arrived before a market was chosen. Ask rather than
                # guess: the wrong guess invites them into the wrong channel.
                return await self._start(tenant_id, update)
            market = available[0]

        config = await self._configs.get_for(tenant_id, self._provider_type, market)
        referral_link = config.referral_link if config else ""

        result = await self._onboarding.submit_uid(
            tenant_id,
            update.user_id,
            market,
            uid,
            username=update.username,
            first_name=update.first_name,
        )
        return ConversationResult([Reply(render(result, referral_link))])


def render(result: OnboardingResult, referral_link: str) -> str:
    """Turn an outcome into words the member can act on.

    Separated from the flow so the copy for every branch can be checked in one
    place — and so a new outcome cannot be added without a reply for it.
    """
    match result.outcome:
        case OnboardingOutcome.INVITED:
            return messages.INVITED.format(invite_link=result.invite_link)
        case OnboardingOutcome.ALREADY_MEMBER:
            return messages.ALREADY_MEMBER.format(invite_link=result.invite_link)
        case OnboardingOutcome.INVALID_UID:
            return messages.INVALID_UID
        case OnboardingOutcome.UID_CLAIMED_BY_ANOTHER_USER:
            return messages.UID_CLAIMED
        case OnboardingOutcome.NOT_REGISTERED:
            return messages.NOT_REGISTERED.format(referral_link=referral_link)
        case OnboardingOutcome.INSUFFICIENT_BALANCE:
            verdict = result.verdict
            assert verdict is not None
            return messages.INSUFFICIENT_BALANCE.format(
                minimum=messages.format_amount(verdict.balance + verdict.shortfall),
                balance=messages.format_amount(verdict.balance),
                shortfall=messages.format_amount(verdict.shortfall),
            )
        case OnboardingOutcome.PROVIDER_UNAVAILABLE:
            return messages.PROVIDER_UNAVAILABLE
        case OnboardingOutcome.NOT_CONFIGURED:
            return messages.NOT_CONFIGURED
    raise AssertionError(f"no reply defined for outcome {result.outcome}")
