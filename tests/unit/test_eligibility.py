"""The referral eligibility rule (PHASE0 §5, §6, §7, §22, §25)."""

from decimal import Decimal

import pytest

from app.application.ports.referral_provider import ReferralCheck
from app.domain.eligibility import (
    EligibilityReason,
    ReferralRules,
    evaluate_referral,
)
from app.domain.enums import ComplianceState

RULES = ReferralRules(minimum_balance=Decimal(300), minimum_trades_per_period=1)


def check(**kwargs) -> ReferralCheck:
    base = {"uid": "123456789", "registered": True, "deposit_total": Decimal(300)}
    return ReferralCheck(**{**base, **kwargs})


def test_a_registered_account_at_the_minimum_qualifies() -> None:
    """`>=`, not `>`: exactly 300 is eligible."""
    verdict = evaluate_referral(check(deposit_total=Decimal(300)), RULES)
    assert verdict.eligible
    assert verdict.compliance_state is ComplianceState.COMPLIANT


@pytest.mark.parametrize("balance", ["300", "500", "1000", "5000", "1000000"])
def test_there_is_no_upper_bound(balance: str) -> None:
    """§6 spells this out. A range check would exclude the best members."""
    assert evaluate_referral(check(deposit_total=Decimal(balance)), RULES).eligible


def test_below_the_minimum_reports_the_shortfall() -> None:
    """The user should be told how much is missing, not just 'no'."""
    verdict = evaluate_referral(check(deposit_total=Decimal("299.99999999")), RULES)
    assert verdict.reason is EligibilityReason.INSUFFICIENT_BALANCE
    assert verdict.shortfall == Decimal("0.00000001")


def test_a_cent_below_the_minimum_is_still_below_it() -> None:
    """Decimal, not float: 299.99999999 must not round up to 300."""
    assert not evaluate_referral(check(deposit_total=Decimal("299.99999999")), RULES).eligible


def test_an_account_outside_the_referral_tree_is_rejected_for_that_reason() -> None:
    verdict = evaluate_referral(check(registered=False, deposit_total=Decimal(10000)), RULES)
    assert verdict.reason is EligibilityReason.NOT_REGISTERED


def test_an_unreachable_provider_is_not_a_user_failure() -> None:
    """§22. This is the verdict that must never lead to a revocation."""
    verdict = evaluate_referral(None, RULES)
    assert verdict.reason is EligibilityReason.PROVIDER_UNAVAILABLE
    assert verdict.compliance_state is ComplianceState.PROVIDER_UNAVAILABLE
    assert verdict.compliance_state is not ComplianceState.NON_COMPLIANT


def test_trading_is_not_required_at_signup() -> None:
    """§25: a member approved today has not had a week to trade yet.

    The prototype's compliance pass ran the same rule at both moments, which is
    how new members were warned on day one.
    """
    verdict = evaluate_referral(check(qualifying_trades=None), RULES, require_trading=False)
    assert verdict.eligible


def test_trading_is_required_during_monitoring() -> None:
    verdict = evaluate_referral(check(qualifying_trades=0), RULES, require_trading=True)
    assert verdict.reason is EligibilityReason.INSUFFICIENT_TRADING


def test_one_qualifying_trade_is_enough_when_that_is_the_rule() -> None:
    verdict = evaluate_referral(check(qualifying_trades=1), RULES, require_trading=True)
    assert verdict.eligible


def test_the_threshold_comes_from_configuration_not_from_code() -> None:
    """§26 BUG-03 was a literal. A balance of 100 passes or fails purely by config."""
    lenient = ReferralRules(minimum_balance=Decimal(10))
    strict = ReferralRules(minimum_balance=Decimal(1000))
    account = check(deposit_total=Decimal(100))
    assert evaluate_referral(account, lenient).eligible
    assert not evaluate_referral(account, strict).eligible


def test_unknown_trading_during_monitoring_is_an_outage_not_an_absence() -> None:
    """Per-fact, not per-call: the provider answered, but not about trades."""
    verdict = evaluate_referral(check(qualifying_trades=None), RULES, require_trading=True)
    assert verdict.reason is EligibilityReason.PROVIDER_UNAVAILABLE
