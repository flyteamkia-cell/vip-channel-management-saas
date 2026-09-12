"""What to do about a member who stopped qualifying (PHASE0 §22–§25).

Pure, like the eligibility rule: state in, decision out. Nothing here sends a
message or touches a channel — it only says what should happen, so every branch
can be tested at a specific instant without a clock, a database or Telegram.

This is the part of the prototype that misbehaved most visibly. Its compliance
window was a 30-minute test value left in production (§26 BUG-02), so members
were warned within the hour and removed the same day. Three rules exist here
specifically to make that class of accident impossible:

* an outage decides nothing,
* a new member is left alone for a configured settling period,
* warnings are spaced, counted, and capped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.domain.eligibility import EligibilityReason, EligibilityVerdict
from app.domain.enums import MembershipStatus


class ComplianceAction(StrEnum):
    NONE = "NONE"
    WARN = "WARN"
    REVOKE = "REVOKE"
    RESTORE = "RESTORE"


class ComplianceSkipReason(StrEnum):
    """Why nothing happened. Worth naming — 'no action' hides real differences."""

    STILL_COMPLIANT = "STILL_COMPLIANT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    ONBOARDING_GRACE = "ONBOARDING_GRACE"
    WARNING_INTERVAL_NOT_ELAPSED = "WARNING_INTERVAL_NOT_ELAPSED"
    NOT_AN_ACTIVE_MEMBERSHIP = "NOT_AN_ACTIVE_MEMBERSHIP"


@dataclass(frozen=True)
class CompliancePolicy:
    """§23, §24, §25 — every timing value configurable, none in code."""

    max_warnings: int = 3
    warning_interval_days: int = 5
    onboarding_grace_days: int = 30


@dataclass(frozen=True)
class MembershipSnapshot:
    """Just enough of a membership to decide, with no ORM attached."""

    status: MembershipStatus
    member_since: datetime
    warnings_sent: int = 0
    last_warning_at: datetime | None = None


@dataclass(frozen=True)
class ComplianceDecision:
    action: ComplianceAction
    skip_reason: ComplianceSkipReason | None = None
    warnings_after: int = 0
    detail: str | None = None


#: Statuses the monitoring pass may act on. A PENDING member has not joined and
#: a REVOKED one has already been dealt with.
_MONITORED = (MembershipStatus.INVITED, MembershipStatus.ACTIVE, MembershipStatus.SUSPENDED)


def _aware(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; treat them as UTC rather than raise."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def decide_compliance(
    membership: MembershipSnapshot,
    verdict: EligibilityVerdict,
    policy: CompliancePolicy,
    now: datetime,
) -> ComplianceDecision:
    if membership.status not in _MONITORED:
        return ComplianceDecision(
            action=ComplianceAction.NONE,
            skip_reason=ComplianceSkipReason.NOT_AN_ACTIVE_MEMBERSHIP,
            warnings_after=membership.warnings_sent,
        )

    if verdict.reason is EligibilityReason.PROVIDER_UNAVAILABLE:
        # §22, and the single most important line in this module. An exchange
        # outage looks exactly like "this member has no balance and no trades"
        # unless the code refuses to read it that way. Nothing moves: not the
        # warning count, not the status, not the clock.
        return ComplianceDecision(
            action=ComplianceAction.NONE,
            skip_reason=ComplianceSkipReason.PROVIDER_UNAVAILABLE,
            warnings_after=membership.warnings_sent,
        )

    if verdict.eligible:
        if membership.warnings_sent > 0 or membership.status is MembershipStatus.SUSPENDED:
            # They fixed it. Clearing the count matters: otherwise a member who
            # dips and recovers three separate times over a year is removed on
            # the third dip, having been compliant throughout.
            return ComplianceDecision(action=ComplianceAction.RESTORE, warnings_after=0)
        return ComplianceDecision(
            action=ComplianceAction.NONE,
            skip_reason=ComplianceSkipReason.STILL_COMPLIANT,
        )

    grace_ends = _aware(membership.member_since) + timedelta(days=policy.onboarding_grace_days)
    if now < grace_ends:
        # §25. Someone who joined today has not had time to fund or trade, and
        # warning them immediately is how the prototype greeted new members.
        return ComplianceDecision(
            action=ComplianceAction.NONE,
            skip_reason=ComplianceSkipReason.ONBOARDING_GRACE,
            warnings_after=membership.warnings_sent,
        )

    if membership.last_warning_at is not None:
        next_allowed = _aware(membership.last_warning_at) + timedelta(
            days=policy.warning_interval_days
        )
        if now < next_allowed:
            # The job may run daily; warnings must not. Without this the cap of
            # three is spent in three days regardless of the configured spacing.
            return ComplianceDecision(
                action=ComplianceAction.NONE,
                skip_reason=ComplianceSkipReason.WARNING_INTERVAL_NOT_ELAPSED,
                warnings_after=membership.warnings_sent,
            )

    if membership.warnings_sent >= policy.max_warnings:
        return ComplianceDecision(
            action=ComplianceAction.REVOKE,
            warnings_after=membership.warnings_sent,
            detail=verdict.reason.value,
        )

    return ComplianceDecision(
        action=ComplianceAction.WARN,
        warnings_after=membership.warnings_sent + 1,
        detail=verdict.reason.value,
    )
