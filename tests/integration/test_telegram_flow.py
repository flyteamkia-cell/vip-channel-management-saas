"""The bot conversation and its webhook, end to end."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import ReferralProgramConfig, TelegramChannel
from app.adapters.persistence.repositories import TelegramUserRepository
from app.adapters.providers.mock import MockReferralProvider
from app.adapters.providers.telegram_mock import MockTelegramProvider
from app.adapters.web.routers.telegram_webhook import parse_update
from app.domain import messages
from app.domain.enums import Market, ProviderType
from app.services.bot_conversation import (
    MARKET_CALLBACK_PREFIX,
    BotConversation,
    IncomingUpdate,
)
from app.services.invite_service import InviteService
from app.services.referral_onboarding import ReferralOnboardingService

UID = "123456789"
TG_USER = 42


async def _configure(
    session: AsyncSession, tenant: UUID, markets: tuple[Market, ...] = (Market.CRYPTO,)
) -> None:
    for index, market in enumerate(markets):
        session.add(
            ReferralProgramConfig(
                tenant_id=tenant,
                provider_type=ProviderType.BITUNIX,
                market=market,
                referral_link=f"https://www.bitunix.com/register?vipCode={market.value}",
                minimum_balance=Decimal(300),
            )
        )
        session.add(
            TelegramChannel(
                tenant_id=tenant, market=market, chat_id=-100111111111 - index
            )
        )
    await session.flush()


def _conversation(session: AsyncSession, referral, telegram) -> BotConversation:
    return BotConversation(
        session, ReferralOnboardingService(session, referral, InviteService(telegram))
    )


@pytest.mark.asyncio
async def test_start_with_one_market_goes_straight_to_the_referral_link(
    tenant_session,
) -> None:
    """A button offering no choice is just an extra tap."""
    tenant = uuid4()
    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        result = await _conversation(
            session, MockReferralProvider(), MockTelegramProvider()
        ).handle(tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text="/start"))

        assert len(result.replies) == 1
        assert "vipCode=CRYPTO" in result.replies[0].text
        assert result.replies[0].reply_markup is None


@pytest.mark.asyncio
async def test_start_with_two_markets_offers_a_choice(tenant_session) -> None:
    tenant = uuid4()
    async with tenant_session(tenant) as session:
        await _configure(session, tenant, markets=(Market.CRYPTO, Market.FOREX))
        result = await _conversation(
            session, MockReferralProvider(), MockTelegramProvider()
        ).handle(tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text="/start"))

        keyboard = result.replies[0].reply_markup["inline_keyboard"]
        data = {row[0]["callback_data"] for row in keyboard}
        assert data == {
            f"{MARKET_CALLBACK_PREFIX}CRYPTO",
            f"{MARKET_CALLBACK_PREFIX}FOREX",
        }


@pytest.mark.asyncio
async def test_an_unconfigured_market_is_never_offered(tenant_session) -> None:
    """A config with no channel is a dead end two steps later."""
    tenant = uuid4()
    async with tenant_session(tenant) as session:
        session.add(
            ReferralProgramConfig(
                tenant_id=tenant,
                provider_type=ProviderType.BITUNIX,
                market=Market.FOREX,
                referral_link="https://x",
                minimum_balance=Decimal(300),
            )
        )
        await _configure(session, tenant, markets=(Market.CRYPTO,))
        result = await _conversation(
            session, MockReferralProvider(), MockTelegramProvider()
        ).handle(tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text="/start"))

        # Only crypto is complete, so the flow skips the menu entirely.
        assert "vipCode=CRYPTO" in result.replies[0].text


@pytest.mark.asyncio
async def test_the_chosen_market_survives_in_the_database(tenant_session) -> None:
    """A redeploy between the button and the UID must not lose the choice."""
    tenant = uuid4()
    async with tenant_session(tenant) as session:
        await _configure(session, tenant, markets=(Market.CRYPTO, Market.FOREX))
        conversation = _conversation(session, MockReferralProvider(), MockTelegramProvider())
        await conversation.handle(
            tenant,
            IncomingUpdate(
                chat_id=TG_USER,
                user_id=TG_USER,
                callback_data=f"{MARKET_CALLBACK_PREFIX}FOREX",
            ),
        )
        await session.commit()

        user = await TelegramUserRepository(session).get_by_telegram_id(tenant, TG_USER)
        assert user is not None
        assert user.pending_market is Market.FOREX


@pytest.mark.asyncio
async def test_the_full_happy_path(tenant_session) -> None:
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500")
    telegram = MockTelegramProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        conversation = _conversation(session, referral, telegram)

        await conversation.handle(
            tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text="/start")
        )
        result = await conversation.handle(
            tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text=UID)
        )
        await session.commit()

        assert "https://t.me/+" in result.replies[0].text
        assert telegram.invites_created


@pytest.mark.asyncio
async def test_persian_digits_in_the_chat(tenant_session) -> None:
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500")

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        conversation = _conversation(session, referral, MockTelegramProvider())
        await conversation.handle(
            tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text="/start")
        )
        result = await conversation.handle(
            tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text="۱۲۳۴۵۶۷۸۹")
        )
        assert "https://t.me/+" in result.replies[0].text


@pytest.mark.asyncio
async def test_a_short_balance_is_explained_with_numbers(tenant_session) -> None:
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="120.5")

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        conversation = _conversation(session, referral, MockTelegramProvider())
        await conversation.handle(
            tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text="/start")
        )
        result = await conversation.handle(
            tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text=UID)
        )

        text = result.replies[0].text
        assert "120.5" in text
        assert "179.5" in text  # the shortfall, so they know what to deposit


@pytest.mark.asyncio
async def test_an_outage_says_it_is_our_fault(tenant_session) -> None:
    tenant = uuid4()
    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        conversation = _conversation(
            session, MockReferralProvider(unavailable=True), MockTelegramProvider()
        )
        await conversation.handle(
            tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text="/start")
        )
        result = await conversation.handle(
            tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text=UID)
        )
        assert result.replies[0].text == messages.PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_a_uid_before_choosing_asks_instead_of_guessing(tenant_session) -> None:
    """The wrong guess invites them into the wrong channel."""
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500")

    async with tenant_session(tenant) as session:
        await _configure(session, tenant, markets=(Market.CRYPTO, Market.FOREX))
        result = await _conversation(session, referral, MockTelegramProvider()).handle(
            tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text=UID)
        )
        assert result.replies[0].reply_markup is not None
        assert referral.calls == []


@pytest.mark.asyncio
async def test_unrecognised_text_asks_for_a_uid(tenant_session) -> None:
    tenant = uuid4()
    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        result = await _conversation(
            session, MockReferralProvider(), MockTelegramProvider()
        ).handle(tenant, IncomingUpdate(chat_id=TG_USER, user_id=TG_USER, text="سلام"))
        assert result.replies[0].text == messages.ASK_FOR_UID


# --------------------------------------------------------------------------- #
# update parsing
# --------------------------------------------------------------------------- #
def test_a_private_message_is_parsed() -> None:
    update = parse_update(
        {
            "message": {
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42, "username": "kia", "first_name": "Kia"},
                "text": "123456789",
            }
        }
    )
    assert update is not None
    assert (update.chat_id, update.user_id, update.text) == (42, 42, "123456789")


def test_a_button_press_is_parsed() -> None:
    update = parse_update(
        {
            "callback_query": {
                "from": {"id": 42},
                "message": {"chat": {"id": 42, "type": "private"}},
                "data": "market:CRYPTO",
            }
        }
    )
    assert update is not None
    assert update.callback_data == "market:CRYPTO"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"channel_post": {"chat": {"id": -100, "type": "channel"}, "text": "hi"}},
        {"message": {"chat": {"id": -100, "type": "supergroup"}, "text": "hi"}},
        {"my_chat_member": {"chat": {"id": -100}}},
    ],
)
def test_updates_outside_the_flow_are_ignored_not_processed(payload) -> None:
    """Telegram sends many update kinds; only private chat drives this flow."""
    assert parse_update(payload) is None
