"""The compliance state machine (PHASE0 §22–§25)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.compliance import (
    ComplianceAction,
    CompliancePolicy,
    ComplianceSkipReason,
    MembershipSnapshot,
    decide_compliance,
)
from app.domain.eligibility import EligibilityReason, EligibilityVerdict
from app.domain.enums import ComplianceState, MembershipStatus

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
POLICY = CompliancePolicy(max_warnings=3, warning_interval_days=5, onboarding_grace_days=30)

COMPLIANT = EligibilityVerdict(
    reason=EligibilityReason.ELIGIBLE,
    compliance_state=ComplianceState.COMPLIANT,
    balance=Decimal(500),
)
SHORT = EligibilityVerdict(
    reason=EligibilityReason.INSUFFICIENT_BALANCE,
    compliance_state=ComplianceState.NON_COMPLIANT,
    balance=Decimal(100),
)
OUTAGE = EligibilityVerdict(
    reason=EligibilityReason.PROVIDER_UNAVAILABLE,
    compliance_state=ComplianceState.PROVIDER_UNAVAILABLE,
)


def member(**kwargs) -> MembershipSnapshot:
    base = {
        "status": MembershipStatus.ACTIVE,
        "member_since": NOW - timedelta(days=200),
        "warnings_sent": 0,
        "last_warning_at": None,
    }
    return MembershipSnapshot(**{**base, **kwargs})


def test_a_compliant_member_is_left_alone() -> None:
    decision = decide_compliance(member(), COMPLIANT, POLICY, NOW)
    assert decision.action is ComplianceAction.NONE
    assert decision.skip_reason is ComplianceSkipReason.STILL_COMPLIANT


def test_an_outage_changes_absolutely_nothing() -> None:
    """§22, and the single most consequential branch in the module.

    An exchange that is down looks identical to a member with no balance and no
    trades unless the code refuses to read it that way.
    """
    decision = decide_compliance(member(warnings_sent=2), OUTAGE, POLICY, NOW)
    assert decision.action is ComplianceAction.NONE
    assert decision.skip_reason is ComplianceSkipReason.PROVIDER_UNAVAILABLE
    assert decision.warnings_after == 2  # not incremented


def test_a_new_member_is_not_warned_on_day_one() -> None:
    """§25. The prototype greeted new members with a warning."""
    decision = decide_compliance(
        member(member_since=NOW - timedelta(days=1)), SHORT, POLICY, NOW
    )
    assert decision.action is ComplianceAction.NONE
    assert decision.skip_reason is ComplianceSkipReason.ONBOARDING_GRACE


def test_the_grace_period_ends_when_configured() -> None:
    just_inside = decide_compliance(
        member(member_since=NOW - timedelta(days=29, hours=23)), SHORT, POLICY, NOW
    )
    just_outside = decide_compliance(
        member(member_since=NOW - timedelta(days=30, seconds=1)), SHORT, POLICY, NOW
    )
    assert just_inside.action is ComplianceAction.NONE
    assert just_outside.action is ComplianceAction.WARN


def test_a_failing_member_past_grace_is_warned_once() -> None:
    decision = decide_compliance(member(), SHORT, POLICY, NOW)
    assert decision.action is ComplianceAction.WARN
    assert decision.warnings_after == 1
    assert decision.detail == "INSUFFICIENT_BALANCE"


def test_warnings_are_spaced_even_when_the_job_runs_daily() -> None:
    """Without this the cap of three is spent in three days."""
    decision = decide_compliance(
        member(warnings_sent=1, last_warning_at=NOW - timedelta(days=1)), SHORT, POLICY, NOW
    )
    assert decision.action is ComplianceAction.NONE
    assert decision.skip_reason is ComplianceSkipReason.WARNING_INTERVAL_NOT_ELAPSED


def test_the_next_warning_lands_once_the_interval_elapses() -> None:
    decision = decide_compliance(
        member(warnings_sent=1, last_warning_at=NOW - timedelta(days=5)), SHORT, POLICY, NOW
    )
    assert decision.action is ComplianceAction.WARN
    assert decision.warnings_after == 2


def test_revocation_only_after_the_cap_is_reached() -> None:
    decision = decide_compliance(
        member(warnings_sent=3, last_warning_at=NOW - timedelta(days=5)), SHORT, POLICY, NOW
    )
    assert decision.action is ComplianceAction.REVOKE


def test_recovering_clears_the_warning_count() -> None:
    """A member who dips and recovers three times over a year is not removed."""
    decision = decide_compliance(member(warnings_sent=2), COMPLIANT, POLICY, NOW)
    assert decision.action is ComplianceAction.RESTORE
    assert decision.warnings_after == 0


def test_a_revoked_membership_is_not_reprocessed() -> None:
    decision = decide_compliance(
        member(status=MembershipStatus.REVOKED), SHORT, POLICY, NOW
    )
    assert decision.action is ComplianceAction.NONE
    assert decision.skip_reason is ComplianceSkipReason.NOT_AN_ACTIVE_MEMBERSHIP


def test_the_whole_path_from_first_failure_to_removal() -> None:
    """Walk the timeline the way it actually happens, day by day.

    With max_warnings=3 and a 5 day interval, removal cannot come sooner than
    15 days after the first warning — which is the property BUG-02 destroyed by
    leaving a 30-minute window in production.
    """
    snapshot = member()
    moment = NOW
    actions = []

    for _ in range(40):
        decision = decide_compliance(snapshot, SHORT, POLICY, moment)
        actions.append((moment, decision.action))
        if decision.action is ComplianceAction.WARN:
            snapshot = member(
                warnings_sent=decision.warnings_after, last_warning_at=moment
            )
        elif decision.action is ComplianceAction.REVOKE:
            break
        moment += timedelta(days=1)

    warns = [m for m, a in actions if a is ComplianceAction.WARN]
    revokes = [m for m, a in actions if a is ComplianceAction.REVOKE]
    assert len(warns) == 3
    assert len(revokes) == 1
    assert (revokes[0] - warns[0]).days == 15


@pytest.mark.parametrize("grace_days", [0, 7, 30, 90])
def test_the_grace_period_is_configuration_not_code(grace_days: int) -> None:
    policy = CompliancePolicy(onboarding_grace_days=grace_days)
    snapshot = member(member_since=NOW - timedelta(days=10))
    decision = decide_compliance(snapshot, SHORT, policy, NOW)
    expected = ComplianceAction.NONE if grace_days > 10 else ComplianceAction.WARN
    assert decision.action is expected
