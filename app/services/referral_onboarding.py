"""The stage 1 flow: a UID arrives, and a member either gets in or is told why.

The whole sequence lives here rather than in a Telegram handler (§33). The
handler's job is to read a message and render a reply; every decision — is the
UID well formed, is it already someone else's, is the account under our
referral, does the balance clear, which channel, which invite — is made in this
service, where it can be tested without Telegram.

The flow the tenant's users follow (as the channel owner described it):
pick a market, receive *that tenant's own* referral link, register at the
exchange through it, send the UID back. That last step is what lands here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import (
    ReferralAccount,
    Subscription,
    TelegramUser,
    VIPMembership,
    utcnow,
)
from app.adapters.persistence.repositories import (
    MembershipRepository,
    ReferralAccountRepository,
    ReferralProgramConfigRepository,
    SubscriptionRepository,
    TelegramChannelRepository,
    TelegramUserRepository,
)
from app.application.exceptions import ProviderUnavailableError
from app.application.ports.referral_provider import ReferralProvider
from app.domain.eligibility import (
    EligibilityReason,
    EligibilityVerdict,
    ReferralRules,
    evaluate_referral,
)
from app.domain.enums import (
    AccessType,
    Market,
    MembershipStatus,
    ReferralAccountStatus,
    SubscriptionStatus,
)
from app.domain.uid import is_valid_bitunix_uid, normalize_uid
from app.services.invite_service import InviteService

#: What a referral member's entitlement is called. Stage 2 adds paid plan codes
#: alongside it; both produce a Subscription, which is why nothing downstream
#: needs to change then.
REFERRAL_PLAN_CODE = "REFERRAL_FREE"


class OnboardingOutcome(StrEnum):
    INVITED = "INVITED"
    ALREADY_MEMBER = "ALREADY_MEMBER"
    INVALID_UID = "INVALID_UID"
    UID_CLAIMED_BY_ANOTHER_USER = "UID_CLAIMED_BY_ANOTHER_USER"
    NOT_REGISTERED = "NOT_REGISTERED"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"


@dataclass(frozen=True)
class OnboardingResult:
    outcome: OnboardingOutcome
    invite_link: str | None = None
    verdict: EligibilityVerdict | None = None
    uid: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome in (OnboardingOutcome.INVITED, OnboardingOutcome.ALREADY_MEMBER)


class ReferralOnboardingService:
    def __init__(
        self,
        session: AsyncSession,
        referral_provider: ReferralProvider,
        invite_service: InviteService,
    ) -> None:
        self._session = session
        self._referral = referral_provider
        self._invites = invite_service
        self._users = TelegramUserRepository(session)
        self._accounts = ReferralAccountRepository(session)
        self._configs = ReferralProgramConfigRepository(session)
        self._subscriptions = SubscriptionRepository(session)
        self._memberships = MembershipRepository(session)
        self._channels = TelegramChannelRepository(session)

    async def submit_uid(
        self,
        tenant_id: UUID,
        telegram_user_id: int,
        market: Market,
        raw_uid: str,
        *,
        username: str | None = None,
        first_name: str | None = None,
    ) -> OnboardingResult:
        provider_type = self._referral.provider_type

        uid = normalize_uid(raw_uid)
        if not is_valid_bitunix_uid(uid):
            # Checked before anything is written or any API is called: a typo
            # should cost nothing and must not create a half-built account.
            return OnboardingResult(outcome=OnboardingOutcome.INVALID_UID, uid=uid)

        config = await self._configs.get_for(tenant_id, provider_type, market)
        channel = await self._channels.get_for_market(tenant_id, market)
        if config is None or channel is None or not config.is_active:
            # The tenant has not finished setting up this market. Nothing here
            # is the user's fault and nothing should be recorded against them.
            return OnboardingResult(outcome=OnboardingOutcome.NOT_CONFIGURED, uid=uid)

        user = await self._ensure_user(tenant_id, telegram_user_id, username, first_name)

        claimed = await self._accounts.get_by_uid(tenant_id, provider_type, uid)
        if claimed is not None and claimed.user_id != user.id:
            # One exchange account backs one member. Without this, a single
            # qualifying balance could carry an unlimited number of people.
            return OnboardingResult(
                outcome=OnboardingOutcome.UID_CLAIMED_BY_ANOTHER_USER, uid=uid
            )

        account = claimed or ReferralAccount(
            tenant_id=tenant_id,
            user_id=user.id,
            provider_type=provider_type,
            market=market,
            uid=uid,
        )

        try:
            check = await self._referral.validate_user(uid)
        except ProviderUnavailableError:
            check = None

        verdict = evaluate_referral(
            check,
            ReferralRules(
                minimum_balance=config.minimum_balance,
                minimum_trades_per_period=config.minimum_trades_per_period,
                trade_period_days=config.trade_period_days,
            ),
            require_trading=False,  # §25: not on day one.
        )

        account.compliance_state = verdict.compliance_state
        account.last_checked_at = utcnow()
        if check is not None:
            # Only overwrite the balance when the provider actually told us one.
            # On an outage `verdict.balance` is zero, and writing that would
            # turn "we could not reach the exchange" into "this member has
            # nothing" the next time anyone reads the row.
            account.last_known_balance = verdict.balance

        if verdict.reason is EligibilityReason.PROVIDER_UNAVAILABLE:
            # §22. The attempt is recorded so a retry has history, but the user
            # is neither rejected nor blamed, and no membership state moves.
            account.status = ReferralAccountStatus.UNVERIFIED
            await self._accounts.save(tenant_id, account)
            return OnboardingResult(
                outcome=OnboardingOutcome.PROVIDER_UNAVAILABLE, verdict=verdict, uid=uid
            )

        if not verdict.eligible:
            account.status = ReferralAccountStatus.REJECTED
            account.rejection_reason = verdict.reason.value
            await self._accounts.save(tenant_id, account)
            outcome = (
                OnboardingOutcome.NOT_REGISTERED
                if verdict.reason is EligibilityReason.NOT_REGISTERED
                else OnboardingOutcome.INSUFFICIENT_BALANCE
            )
            return OnboardingResult(outcome=outcome, verdict=verdict, uid=uid)

        account.status = ReferralAccountStatus.VERIFIED
        account.rejection_reason = None
        account.verified_at = utcnow()
        await self._accounts.save(tenant_id, account)

        subscription = await self._ensure_subscription(tenant_id, user.id, market)
        membership = await self._ensure_membership(
            tenant_id, user.id, channel.id, subscription.id
        )
        already_in = membership.status is MembershipStatus.ACTIVE

        invite = await self._invites.issue(tenant_id, membership, channel)
        await self._memberships.save(tenant_id, membership)

        return OnboardingResult(
            outcome=(
                OnboardingOutcome.ALREADY_MEMBER if already_in else OnboardingOutcome.INVITED
            ),
            invite_link=invite.link,
            verdict=verdict,
            uid=uid,
        )

    async def _ensure_user(
        self,
        tenant_id: UUID,
        telegram_user_id: int,
        username: str | None,
        first_name: str | None,
    ) -> TelegramUser:
        user = await self._users.get_by_telegram_id(tenant_id, telegram_user_id)
        if user is None:
            user = TelegramUser(
                tenant_id=tenant_id,
                telegram_user_id=telegram_user_id,
                username=username,
                first_name=first_name,
            )
            return await self._users.save(tenant_id, user)
        # Display names change; keep the latest without losing the row.
        user.username = username or user.username
        user.first_name = first_name or user.first_name
        return user

    async def _ensure_subscription(
        self, tenant_id: UUID, user_id: UUID, market: Market
    ) -> Subscription:
        existing = await self._subscriptions.get_active_for_user(tenant_id, user_id, market)
        if existing is not None:
            existing.status = SubscriptionStatus.ACTIVE
            existing.starts_at = existing.starts_at or utcnow()
            return existing
        return await self._subscriptions.save(
            tenant_id,
            Subscription(
                tenant_id=tenant_id,
                user_id=user_id,
                market=market,
                access_type=AccessType.REFERRAL,
                plan_code=REFERRAL_PLAN_CODE,
                status=SubscriptionStatus.ACTIVE,
                starts_at=utcnow(),
                # No ends_at: a referral entitlement runs while the member stays
                # eligible, which the monitoring job decides (§21).
            ),
        )

    async def _ensure_membership(
        self, tenant_id: UUID, user_id: UUID, channel_id: UUID, subscription_id: UUID
    ) -> VIPMembership:
        existing = await self._memberships.get_for_user_and_channel(
            tenant_id, user_id, channel_id
        )
        if existing is not None:
            existing.subscription_id = subscription_id
            if existing.status in (MembershipStatus.REVOKED, MembershipStatus.EXPIRED):
                # A returning member starts clean: the old revocation must not
                # count towards the warning budget of their new spell (§24).
                existing.status = MembershipStatus.PENDING
                existing.revoked_at = None
                existing.revocation_reason = None
                existing.warnings_sent = 0
                existing.last_warning_at = None
            return existing
        return await self._memberships.save(
            tenant_id,
            VIPMembership(
                tenant_id=tenant_id,
                user_id=user_id,
                channel_id=channel_id,
                subscription_id=subscription_id,
                status=MembershipStatus.PENDING,
            ),
        )
