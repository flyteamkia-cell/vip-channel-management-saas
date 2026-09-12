"""The periodic pass that keeps membership honest (PHASE0 §21–§25, §32).

Once per period, for one tenant: re-check every monitored member against the
exchange, decide what the compliance rules say, and carry it out. This is the
job that makes the product self-maintaining — without it the bot invites people
and never cleans up.

Everything it decides comes from two pure functions (evaluate_referral and
decide_compliance). What lives here is only the sequencing and the side
effects, which is what makes the rules testable at an instant and this class
testable with mocks.

Safety properties, all of them from §32:

* the period is claimed before any work, so two instances cannot both run it;
* the claim is keyed by period, so a replay is a no-op rather than a second
  round of warnings;
* a member whose provider check fails is skipped entirely, never revoked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import (
    TelegramChannel,
    TradingActivitySnapshot,
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
from app.application.ports.telegram_provider import TelegramProvider
from app.domain import messages
from app.domain.compliance import (
    ComplianceAction,
    ComplianceDecision,
    CompliancePolicy,
    ComplianceSkipReason,
    MembershipSnapshot,
    decide_compliance,
)
from app.domain.eligibility import ReferralRules, evaluate_referral
from app.domain.enums import (
    MembershipStatus,
    SubscriptionStatus,
)
from app.jobs.period_lock import claim_period, finish, period_start_for

JOB_NAME = "referral_compliance_check"


@dataclass
class MonitorReport:
    claimed: bool
    period_start: datetime | None = None
    processed: int = 0
    warned: int = 0
    revoked: int = 0
    restored: int = 0
    skipped_unavailable: int = 0


class MembershipMonitor:
    def __init__(
        self,
        session: AsyncSession,
        referral_provider: ReferralProvider,
        telegram: TelegramProvider,
        policy: CompliancePolicy | None = None,
        period: timedelta = timedelta(days=7),
    ) -> None:
        self._session = session
        self._referral = referral_provider
        self._telegram = telegram
        self._policy = policy or CompliancePolicy()
        self._period = period
        self._memberships = MembershipRepository(session)
        self._accounts = ReferralAccountRepository(session)
        self._configs = ReferralProgramConfigRepository(session)
        self._channels = TelegramChannelRepository(session)
        self._subscriptions = SubscriptionRepository(session)
        self._users = TelegramUserRepository(session)

    async def run(self, tenant_id: UUID, *, now: datetime | None = None) -> MonitorReport:
        moment = now or utcnow()
        period_start = period_start_for(moment, self._period)

        execution = await claim_period(self._session, tenant_id, JOB_NAME, period_start)
        if execution is None:
            # Another instance owns this period, or it already ran. Standing
            # down is the correct outcome, not an error.
            return MonitorReport(claimed=False, period_start=period_start)

        report = MonitorReport(claimed=True, period_start=period_start)
        try:
            for membership in await self._memberships.list_by_status(
                tenant_id, MembershipStatus.INVITED, MembershipStatus.ACTIVE,
                MembershipStatus.SUSPENDED,
            ):
                await self._process(tenant_id, membership, period_start, moment, report)
        except Exception as exc:
            finish(execution, error=f"{type(exc).__name__}: {exc}")
            raise

        execution.processed = report.processed
        execution.warned = report.warned
        execution.revoked = report.revoked
        execution.skipped_unavailable = report.skipped_unavailable
        finish(execution)
        return report

    async def _process(
        self,
        tenant_id: UUID,
        membership: VIPMembership,
        period_start: datetime,
        moment: datetime,
        report: MonitorReport,
    ) -> None:
        report.processed += 1

        accounts = await self._accounts.list_for_user(tenant_id, membership.user_id)
        if not accounts:
            return
        account = accounts[0]

        config = await self._configs.get_for(tenant_id, account.provider_type, account.market)
        if config is None:
            return

        try:
            check = await self._referral.validate_user(account.uid)
        except ProviderUnavailableError:
            check = None

        verdict = evaluate_referral(
            check,
            ReferralRules(
                minimum_balance=config.minimum_balance,
                minimum_trades_per_period=config.minimum_trades_per_period,
                trade_period_days=config.trade_period_days,
            ),
            # On the monitoring pass the trading rule applies (§7, §21); at
            # signup it does not (§25).
            require_trading=True,
        )

        account.compliance_state = verdict.compliance_state
        account.last_checked_at = moment
        if check is not None:
            account.last_known_balance = verdict.balance
            self._session.add(
                TradingActivitySnapshot(
                    tenant_id=tenant_id,
                    referral_account_id=account.id,
                    period_start=period_start,
                    period_end=period_start + self._period,
                    qualifying_trades=check.qualifying_trades or 0,
                    balance=check.deposit_total,
                    still_under_referral=check.registered,
                    provider_state=verdict.compliance_state,
                )
            )

        policy = CompliancePolicy(
            max_warnings=self._policy.max_warnings,
            warning_interval_days=self._policy.warning_interval_days,
            onboarding_grace_days=config.compliance_grace_period_days,
        )
        decision = decide_compliance(
            MembershipSnapshot(
                status=membership.status,
                member_since=membership.joined_at or membership.created_at,
                warnings_sent=membership.warnings_sent,
                last_warning_at=membership.last_warning_at,
            ),
            verdict,
            policy,
            moment,
        )

        await self._apply(tenant_id, membership, account.market, decision, moment, report, policy)

    async def _apply(
        self,
        tenant_id: UUID,
        membership: VIPMembership,
        market,
        decision: ComplianceDecision,
        moment: datetime,
        report: MonitorReport,
        policy: CompliancePolicy,
    ) -> None:
        if decision.action is ComplianceAction.NONE:
            if decision.skip_reason is ComplianceSkipReason.PROVIDER_UNAVAILABLE:
                report.skipped_unavailable += 1
            return

        user = await self._users.get_by_id(tenant_id, membership.user_id)
        chat_id = user.telegram_user_id if user else None
        reason_text = messages.REASON_TEXT.get(decision.detail or "", "")

        if decision.action is ComplianceAction.RESTORE:
            membership.warnings_sent = 0
            membership.last_warning_at = None
            if membership.status is MembershipStatus.SUSPENDED:
                membership.status = MembershipStatus.ACTIVE
            report.restored += 1
            if chat_id:
                await self._telegram.send_message(chat_id, messages.MEMBERSHIP_RESTORED)
            return

        if decision.action is ComplianceAction.WARN:
            membership.warnings_sent = decision.warnings_after
            membership.last_warning_at = moment
            report.warned += 1
            if chat_id:
                await self._telegram.send_message(
                    chat_id,
                    messages.COMPLIANCE_WARNING.format(
                        warning_number=decision.warnings_after,
                        max_warnings=policy.max_warnings,
                        reason_text=reason_text,
                    ),
                )
            return

        # REVOKE
        channel: TelegramChannel | None = await self._channels.get_for_market(tenant_id, market)
        if channel is not None:
            await self._telegram.ban_chat_member(channel.chat_id, chat_id or 0)
            # Telegram's ban is sticky: without the unban a future renewal is
            # silently impossible, which is a support ticket nobody can explain.
            await self._telegram.unban_chat_member(channel.chat_id, chat_id or 0)

        membership.status = MembershipStatus.REVOKED
        membership.revoked_at = moment
        membership.revocation_reason = decision.detail
        membership.invite_link = None
        report.revoked += 1

        subscription = await self._subscriptions.get_active_for_user(
            tenant_id, membership.user_id, market
        )
        if subscription is not None:
            # The entitlement expires; the payment history it came from, if any,
            # is never touched (§12).
            subscription.status = SubscriptionStatus.EXPIRED
            subscription.ends_at = moment

        if chat_id:
            await self._telegram.send_message(
                chat_id, messages.MEMBERSHIP_REVOKED.format(reason_text=reason_text)
            )
