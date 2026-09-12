"""The scheduled compliance pass, against real PostgreSQL (PHASE0 §21–§25, §32)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import (
    JobExecution,
    ReferralProgramConfig,
    TelegramChannel,
    TradingActivitySnapshot,
)
from app.adapters.persistence.repositories import (
    MembershipRepository,
    SubscriptionRepository,
)
from app.adapters.providers.mock import MockReferralProvider
from app.adapters.providers.telegram_mock import MockTelegramProvider
from app.domain import messages
from app.domain.enums import (
    JobRunState,
    Market,
    MembershipStatus,
    ProviderType,
    SubscriptionStatus,
)
from app.jobs.membership_monitor import JOB_NAME, MembershipMonitor
from app.jobs.period_lock import claim_period, period_start_for
from app.services.invite_service import InviteService
from app.services.referral_onboarding import ReferralOnboardingService

UID = "123456789"
CHAT_ID = -1001234567890
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
WEEK = timedelta(days=7)


async def _configure(session: AsyncSession, tenant: UUID, grace_days: int = 30) -> None:
    session.add(
        ReferralProgramConfig(
            tenant_id=tenant,
            provider_type=ProviderType.BITUNIX,
            market=Market.CRYPTO,
            referral_link="https://www.bitunix.com/register?vipCode=OWNER",
            minimum_balance=Decimal(300),
            minimum_trades_per_period=1,
            compliance_grace_period_days=grace_days,
        )
    )
    session.add(TelegramChannel(tenant_id=tenant, market=Market.CRYPTO, chat_id=CHAT_ID))
    await session.flush()


async def _enroll(
    session: AsyncSession, tenant: UUID, referral: MockReferralProvider, joined_days_ago: int
) -> None:
    await ReferralOnboardingService(
        session, referral, InviteService(MockTelegramProvider())
    ).submit_uid(tenant, telegram_user_id=42, market=Market.CRYPTO, raw_uid=UID)
    membership = (await MembershipRepository(session).list_all(tenant))[0]
    membership.status = MembershipStatus.ACTIVE
    membership.joined_at = NOW - timedelta(days=joined_days_ago)
    await session.flush()


@pytest.mark.asyncio
async def test_a_still_qualifying_member_is_untouched(tenant_session) -> None:
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500", qualifying_trades=3)
    telegram = MockTelegramProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        await _enroll(session, tenant, referral, joined_days_ago=200)
        report = await MembershipMonitor(session, referral, telegram).run(tenant, now=NOW)
        await session.commit()

        assert report.claimed is True
        assert (report.processed, report.warned, report.revoked) == (1, 0, 0)
        assert telegram.messages == []


@pytest.mark.asyncio
async def test_a_member_who_stopped_trading_is_warned_not_removed(tenant_session) -> None:
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500", qualifying_trades=0)
    telegram = MockTelegramProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        await _enroll(session, tenant, referral, joined_days_ago=200)
        report = await MembershipMonitor(session, referral, telegram).run(tenant, now=NOW)
        await session.commit()

        assert (report.warned, report.revoked) == (1, 0)
        membership = (await MembershipRepository(session).list_all(tenant))[0]
        assert membership.status is MembershipStatus.ACTIVE
        assert membership.warnings_sent == 1
        assert len(telegram.messages) == 1
        # The member is told which warning this is, out of how many, and why --
        # a bare "you are non-compliant" gives them nothing to act on.
        assert "1" in telegram.messages[0].text
        assert "3" in telegram.messages[0].text
        assert messages.REASON_TEXT["INSUFFICIENT_TRADING"] in telegram.messages[0].text


@pytest.mark.asyncio
async def test_a_brand_new_member_is_not_warned(tenant_session) -> None:
    """§25 — the prototype greeted new members with a warning."""
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500", qualifying_trades=0)
    telegram = MockTelegramProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        await _enroll(session, tenant, referral, joined_days_ago=1)
        report = await MembershipMonitor(session, referral, telegram).run(tenant, now=NOW)
        await session.commit()

        assert (report.warned, report.revoked) == (0, 0)
        assert telegram.messages == []


@pytest.mark.asyncio
async def test_an_exchange_outage_never_removes_anyone(tenant_session) -> None:
    """§22 at the job level. This is the failure mode that loses paying members."""
    tenant = uuid4()
    good = MockReferralProvider()
    good.register(UID, deposit_total="500", qualifying_trades=3)
    telegram = MockTelegramProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        await _enroll(session, tenant, good, joined_days_ago=200)
        await session.commit()

        down = MockReferralProvider(unavailable=True)
        report = await MembershipMonitor(session, down, telegram).run(tenant, now=NOW)
        await session.commit()

        assert report.skipped_unavailable == 1
        assert (report.warned, report.revoked) == (0, 0)
        membership = (await MembershipRepository(session).list_all(tenant))[0]
        assert membership.status is MembershipStatus.ACTIVE
        assert membership.warnings_sent == 0
        assert telegram.messages == []


@pytest.mark.asyncio
async def test_removal_bans_and_then_unbans(tenant_session) -> None:
    """Telegram's ban is sticky; without the unban a renewal is impossible."""
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500", qualifying_trades=0)
    telegram = MockTelegramProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        await _enroll(session, tenant, referral, joined_days_ago=200)
        membership = (await MembershipRepository(session).list_all(tenant))[0]
        membership.warnings_sent = 3
        membership.last_warning_at = NOW - timedelta(days=6)
        await session.commit()

        report = await MembershipMonitor(session, referral, telegram).run(tenant, now=NOW)
        await session.commit()

        assert report.revoked == 1
        assert telegram.banned == [(CHAT_ID, 42)]
        assert telegram.unbanned == [(CHAT_ID, 42)]

        refreshed = (await MembershipRepository(session).list_all(tenant))[0]
        assert refreshed.status is MembershipStatus.REVOKED
        assert refreshed.invite_link is None

        subscription = (await SubscriptionRepository(session).list_all(tenant))[0]
        assert subscription.status is SubscriptionStatus.EXPIRED


@pytest.mark.asyncio
async def test_running_the_same_period_twice_does_nothing_the_second_time(
    tenant_session,
) -> None:
    """§32 — a replay must not send a second round of warnings."""
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500", qualifying_trades=0)
    telegram = MockTelegramProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        await _enroll(session, tenant, referral, joined_days_ago=200)

        first = await MembershipMonitor(session, referral, telegram).run(tenant, now=NOW)
        await session.commit()
        second = await MembershipMonitor(session, referral, telegram).run(
            tenant, now=NOW + timedelta(hours=2)
        )
        await session.commit()

        assert first.claimed is True
        assert second.claimed is False
        assert len(telegram.messages) == 1

        membership = (await MembershipRepository(session).list_all(tenant))[0]
        assert membership.warnings_sent == 1


@pytest.mark.asyncio
async def test_a_second_instance_cannot_claim_the_same_period(tenant_session) -> None:
    """The unique key is the lock: one insert wins, the other stands down."""
    tenant = uuid4()
    period = period_start_for(NOW, WEEK)

    async with tenant_session(tenant) as session:
        first = await claim_period(session, tenant, JOB_NAME, period)
        second = await claim_period(session, tenant, JOB_NAME, period)
        await session.commit()

        assert first is not None
        assert second is None
        # The loser's failure must not have poisoned the winner's work.
        rows = (await session.execute(select(JobExecution))).scalars().all()
        assert len(rows) == 1
        assert rows[0].state is JobRunState.RUNNING


@pytest.mark.asyncio
async def test_different_tenants_do_not_block_each_other(tenant_session) -> None:
    a, b = uuid4(), uuid4()
    period = period_start_for(NOW, WEEK)

    async with tenant_session(a) as session:
        assert await claim_period(session, a, JOB_NAME, period) is not None
        await session.commit()
    async with tenant_session(b) as session:
        assert await claim_period(session, b, JOB_NAME, period) is not None
        await session.commit()


@pytest.mark.asyncio
async def test_a_trading_snapshot_is_recorded_for_the_period(tenant_session) -> None:
    """§8 — provider-sourced activity, never a user's screenshot."""
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="750.25", qualifying_trades=4)
    telegram = MockTelegramProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        await _enroll(session, tenant, referral, joined_days_ago=200)
        await MembershipMonitor(session, referral, telegram).run(tenant, now=NOW)
        await session.commit()

        snapshots = (
            (await session.execute(select(TradingActivitySnapshot))).scalars().all()
        )
        assert len(snapshots) == 1
        assert snapshots[0].qualifying_trades == 4
        assert snapshots[0].balance == Decimal("750.25")
        assert snapshots[0].still_under_referral is True


@pytest.mark.asyncio
async def test_the_run_is_recorded_with_its_counts(tenant_session) -> None:
    tenant = uuid4()
    referral = MockReferralProvider()
    referral.register(UID, deposit_total="500", qualifying_trades=0)

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        await _enroll(session, tenant, referral, joined_days_ago=200)
        await MembershipMonitor(session, referral, MockTelegramProvider()).run(
            tenant, now=NOW
        )
        await session.commit()

        execution = (await session.execute(select(JobExecution))).scalars().one()
        assert execution.state is JobRunState.SUCCEEDED
        assert (execution.processed, execution.warned, execution.revoked) == (1, 1, 0)
        assert execution.finished_at is not None


@pytest.mark.asyncio
async def test_recovering_clears_warnings_and_tells_the_member(tenant_session) -> None:
    tenant = uuid4()
    failing = MockReferralProvider()
    failing.register(UID, deposit_total="500", qualifying_trades=0)
    telegram = MockTelegramProvider()

    async with tenant_session(tenant) as session:
        await _configure(session, tenant)
        await _enroll(session, tenant, failing, joined_days_ago=200)
        await MembershipMonitor(session, failing, telegram).run(tenant, now=NOW)
        await session.commit()

        recovered = MockReferralProvider()
        recovered.register(UID, deposit_total="500", qualifying_trades=5)
        report = await MembershipMonitor(session, recovered, telegram).run(
            tenant, now=NOW + WEEK
        )
        await session.commit()

        assert report.restored == 1
        membership = (await MembershipRepository(session).list_all(tenant))[0]
        assert membership.warnings_sent == 0
        assert membership.status is MembershipStatus.ACTIVE


@pytest.mark.asyncio
async def test_the_period_boundary_is_stable_across_instances(tenant_session) -> None:
    """Two instances a few hours apart must compute the same period."""
    early = period_start_for(datetime(2026, 9, 12, 0, 5, tzinfo=UTC), WEEK)
    late = period_start_for(datetime(2026, 9, 12, 23, 55, tzinfo=UTC), WEEK)
    assert early == late
    assert period_start_for(datetime(2026, 9, 20, 0, 5, tzinfo=UTC), WEEK) != early
