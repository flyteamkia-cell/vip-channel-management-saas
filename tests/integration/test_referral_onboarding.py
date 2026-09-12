"""The stage 1 flow end to end, against real PostgreSQL with mock providers."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import (
    ReferralProgramConfig,
    TelegramChannel,
)
from app.adapters.persistence.repositories import (
    MembershipRepository,
    ReferralAccountRepository,
    SubscriptionRepository,
)
from app.adapters.providers.mock import MockReferralProvider
from app.adapters.providers.telegram_mock import MockTelegramProvider
from app.domain.enums import (
    AccessType,
    ComplianceState,
    Market,
    MembershipStatus,
    ProviderType,
    ReferralAccountStatus,
    SubscriptionStatus,
)
from app.services.invite_service import InviteService
from app.services.referral_onboarding import (
    OnboardingOutcome,
    ReferralOnboardingService,
)

UID = "123456789"
CHAT_ID = -1001234567890


async def _configure(
    session: AsyncSession, tenant_id: UUID, minimum: Decimal = Decimal(300)
) -> None:
    session.add(
        ReferralProgramConfig(
            tenant_id=tenant_id,
            provider_type=ProviderType.BITUNIX,
            market=Market.CRYPTO,
            referral_link="https://www.bitunix.com/register?vipCode=OWNER",
            minimum_balance=minimum,
        )
    )
    session.add(
        TelegramChannel(tenant_id=tenant_id, market=Market.CRYPTO, chat_id=CHAT_ID)
    )
    await session.flush()


def _service(
    session: AsyncSession,
    referral: MockReferralProvider,
    telegram: MockTelegramProvider,
) -> ReferralOnboardingService:
    return ReferralOnboardingService(session, referral, InviteService(telegram))


@pytest.mark.asyncio
async def test_a_qualifying_uid_gets_an_invite_and_a_full_record(tenant_session) -> None:
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500")
    telegram = MockTelegramProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        result = await _service(session, referral, telegram).submit_uid(
            tenant, telegram_user_id=42, market=Market.CRYPTO, raw_uid=UID
        )
        await session.commit()

        assert result.outcome is OnboardingOutcome.INVITED
        assert result.invite_link is not None
        assert telegram.invites_created == [(CHAT_ID, 1)]

        account = await ReferralAccountRepository(session).get_by_uid(
            tenant, ProviderType.BITUNIX, UID
        )
        assert account is not None
        assert account.status is ReferralAccountStatus.VERIFIED
        assert account.compliance_state is ComplianceState.COMPLIANT
        assert account.last_known_balance == Decimal(500)

        memberships = await MembershipRepository(session).list_by_status(
            tenant, MembershipStatus.INVITED
        )
        assert len(memberships) == 1
        subs = await SubscriptionRepository(session).list_all(tenant)
        assert len(subs) == 1
        # Referral and payment both land on Subscription -- this is the seam
        # that lets stage 2 arrive without touching membership.
        assert subs[0].access_type is AccessType.REFERRAL
        assert subs[0].status is SubscriptionStatus.ACTIVE
        assert subs[0].ends_at is None


@pytest.mark.asyncio
async def test_persian_digits_are_accepted(tenant_session) -> None:
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="300")

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        result = await _service(session, referral, MockTelegramProvider()).submit_uid(
            tenant, telegram_user_id=42, market=Market.CRYPTO, raw_uid="۱۲۳۴۵۶۷۸۹"
        )
        assert result.outcome is OnboardingOutcome.INVITED


@pytest.mark.asyncio
async def test_a_malformed_uid_costs_nothing(tenant_session) -> None:
    """No API call, no rows -- a typo must not build half an account."""
    tenant = uuid4()
    referral = MockReferralProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        result = await _service(session, referral, MockTelegramProvider()).submit_uid(
            tenant, telegram_user_id=42, market=Market.CRYPTO, raw_uid="12345"
        )

        assert result.outcome is OnboardingOutcome.INVALID_UID
        assert referral.calls == []
        assert await ReferralAccountRepository(session).list_all(tenant) == []


@pytest.mark.asyncio
async def test_a_short_balance_is_rejected_with_the_shortfall(tenant_session) -> None:
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="299.5")

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        result = await _service(session, referral, MockTelegramProvider()).submit_uid(
            tenant, telegram_user_id=42, market=Market.CRYPTO, raw_uid=UID
        )
        await session.commit()

        assert result.outcome is OnboardingOutcome.INSUFFICIENT_BALANCE
        assert result.verdict is not None
        assert result.verdict.shortfall == Decimal("0.5")
        account = await ReferralAccountRepository(session).get_by_uid(
            tenant, ProviderType.BITUNIX, UID
        )
        assert account is not None
        assert account.status is ReferralAccountStatus.REJECTED
        assert await MembershipRepository(session).list_all(tenant) == []


@pytest.mark.asyncio
async def test_an_exchange_outage_does_not_reject_the_user(tenant_session) -> None:
    """§22 at the flow level: nothing is decided, nothing is blamed."""
    tenant = uuid4()
    referral = MockReferralProvider(unavailable=True)

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        result = await _service(session, referral, MockTelegramProvider()).submit_uid(
            tenant, telegram_user_id=42, market=Market.CRYPTO, raw_uid=UID
        )
        await session.commit()

        assert result.outcome is OnboardingOutcome.PROVIDER_UNAVAILABLE
        account = await ReferralAccountRepository(session).get_by_uid(
            tenant, ProviderType.BITUNIX, UID
        )
        assert account is not None
        assert account.status is ReferralAccountStatus.UNVERIFIED
        assert account.compliance_state is ComplianceState.PROVIDER_UNAVAILABLE
        assert account.rejection_reason is None


@pytest.mark.asyncio
async def test_an_outage_never_overwrites_a_known_balance(tenant_session) -> None:
    """Writing zero would turn 'could not reach the exchange' into 'has nothing'."""
    tenant = uuid4()
    good = MockReferralProvider()
    good.register(UID, deposit_total="800")

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        await _service(session, good, MockTelegramProvider()).submit_uid(
            tenant, telegram_user_id=42, market=Market.CRYPTO, raw_uid=UID
        )
        await session.commit()

        down = MockReferralProvider(unavailable=True)
        await _service(session, down, MockTelegramProvider()).submit_uid(
            tenant, telegram_user_id=42, market=Market.CRYPTO, raw_uid=UID
        )
        await session.commit()

        account = await ReferralAccountRepository(session).get_by_uid(
            tenant, ProviderType.BITUNIX, UID
        )
        assert account is not None
        assert account.last_known_balance == Decimal(800)


@pytest.mark.asyncio
async def test_one_exchange_account_backs_one_member(tenant_session) -> None:
    """Otherwise a single qualifying balance carries an unlimited crowd."""
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500")

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        service = _service(session, referral, MockTelegramProvider())
        await service.submit_uid(tenant, 42, Market.CRYPTO, UID)
        await session.commit()

        result = await service.submit_uid(tenant, 99, Market.CRYPTO, UID)
        assert result.outcome is OnboardingOutcome.UID_CLAIMED_BY_ANOTHER_USER


@pytest.mark.asyncio
async def test_resubmitting_is_idempotent(tenant_session) -> None:
    """A user tapping twice must not mint a second single-use invite."""
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500")
    telegram = MockTelegramProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        service = _service(session, referral, telegram)
        first = await service.submit_uid(tenant, 42, Market.CRYPTO, UID)
        await session.commit()
        second = await service.submit_uid(tenant, 42, Market.CRYPTO, UID)
        await session.commit()

        assert second.invite_link == first.invite_link
        assert len(telegram.invites_created) == 1
        assert len(await MembershipRepository(session).list_all(tenant)) == 1


@pytest.mark.asyncio
async def test_an_unconfigured_market_is_not_the_users_fault(tenant_session) -> None:
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500")

    async with tenant_session(tenant) as session:
        # No ReferralProgramConfig, no channel.
        result = await _service(session, referral, MockTelegramProvider()).submit_uid(
            tenant, 42, Market.CRYPTO, UID
        )
        assert result.outcome is OnboardingOutcome.NOT_CONFIGURED
        assert referral.calls == []


@pytest.mark.asyncio
async def test_the_threshold_is_the_tenants_own(tenant_session) -> None:
    """Two tenants, same UID balance, different answers -- because config differs."""
    lenient, strict = uuid4(), uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="100")

    async with tenant_session(lenient) as session:
        await _configure(session, lenient, minimum=Decimal(50))
        result = await _service(session, referral, MockTelegramProvider()).submit_uid(
            lenient, 42, Market.CRYPTO, UID
        )
        await session.commit()
        assert result.outcome is OnboardingOutcome.INVITED

    async with tenant_session(strict) as session:
        await _configure(session, strict, minimum=Decimal(1000))
        result = await _service(session, referral, MockTelegramProvider()).submit_uid(
            strict, 42, Market.CRYPTO, UID
        )
        await session.commit()
        assert result.outcome is OnboardingOutcome.INSUFFICIENT_BALANCE


@pytest.mark.asyncio
async def test_a_returning_member_starts_with_a_clean_warning_count(
    tenant_session,
) -> None:
    """§24: an old revocation must not count against a new spell."""
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500")

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        service = _service(session, referral, MockTelegramProvider())
        await service.submit_uid(tenant, 42, Market.CRYPTO, UID)
        await session.commit()

        memberships = await MembershipRepository(session).list_all(tenant)
        membership = memberships[0]
        membership.status = MembershipStatus.REVOKED
        membership.warnings_sent = 3
        membership.revocation_reason = "balance fell"
        await session.commit()

        await service.submit_uid(tenant, 42, Market.CRYPTO, UID)
        await session.commit()

        refreshed = (await MembershipRepository(session).list_all(tenant))[0]
        assert refreshed.warnings_sent == 0
        assert refreshed.revocation_reason is None
        assert refreshed.status is MembershipStatus.INVITED
