"""Who qualifies for VIP access through a referral — the whole rule, in one place.

Pure: it takes a provider's answer and a tenant's configuration and returns a
verdict. No database, no HTTP, no clock beyond what is handed in. That is what
makes the rule testable exhaustively and cheap to reason about, and it is the
opposite of the prototype, where the same decision was spread across four IF
nodes on three branches and drifted apart (§26 BUG-03, BUG-04).

The verdict deliberately carries a reason. "Not eligible" is not one thing: a
user who never registered under our link needs different words from one whose
balance is short, and a member we could not check at all must not be told
anything (§22).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.application.ports.referral_provider import ReferralCheck
from app.domain.enums import ComplianceState


class EligibilityReason(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NOT_REGISTERED = "NOT_REGISTERED"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    INSUFFICIENT_TRADING = "INSUFFICIENT_TRADING"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


@dataclass(frozen=True)
class ReferralRules:
    """The tenant's configured thresholds, lifted out of the ORM row.

    A plain value object so the rule can be tested without a database, and so
    nothing in here can lazily load or accidentally hold a session.
    """

    minimum_balance: Decimal
    minimum_trades_per_period: int = 1
    trade_period_days: int = 7


@dataclass(frozen=True)
class EligibilityVerdict:
    reason: EligibilityReason
    compliance_state: ComplianceState
    balance: Decimal = Decimal(0)
    shortfall: Decimal = Decimal(0)

    @property
    def eligible(self) -> bool:
        return self.reason is EligibilityReason.ELIGIBLE


def evaluate_referral(
    check: ReferralCheck | None,
    rules: ReferralRules,
    *,
    require_trading: bool = False,
) -> EligibilityVerdict:
    """Decide whether one referral account qualifies.

    `check is None` means the provider could not be reached. It maps to
    PROVIDER_UNAVAILABLE and never to a failure the user is blamed for — §22 in
    one line. Callers treat that verdict as "leave the previous decision
    standing", not as grounds to revoke.

    There is no upper bound on balance. §6 is explicit: eligibility is
    `balance >= minimum`, and a richer member is not less eligible. Writing it
    as a range, as some referral systems do, would silently exclude exactly the
    traders worth keeping.

    `require_trading` is off during sign-up and on during monitoring: at the
    moment someone joins they have not had a week to trade yet, so applying
    §7's rule then would reject every new member on day one (§25).
    """
    if check is None:
        return EligibilityVerdict(
            reason=EligibilityReason.PROVIDER_UNAVAILABLE,
            compliance_state=ComplianceState.PROVIDER_UNAVAILABLE,
        )

    if not check.registered:
        return EligibilityVerdict(
            reason=EligibilityReason.NOT_REGISTERED,
            compliance_state=ComplianceState.NON_COMPLIANT,
            balance=check.deposit_total,
        )

    if check.deposit_total < rules.minimum_balance:
        return EligibilityVerdict(
            reason=EligibilityReason.INSUFFICIENT_BALANCE,
            compliance_state=ComplianceState.NON_COMPLIANT,
            balance=check.deposit_total,
            shortfall=rules.minimum_balance - check.deposit_total,
        )

    if require_trading:
        trades = check.qualifying_trades
        if trades is None:
            # The provider answered about the account but told us nothing about
            # trading. That is still "we could not tell", not "they did not
            # trade" -- the §22 distinction applies per fact, not per call.
            return EligibilityVerdict(
                reason=EligibilityReason.PROVIDER_UNAVAILABLE,
                compliance_state=ComplianceState.PROVIDER_UNAVAILABLE,
                balance=check.deposit_total,
            )
        if trades < rules.minimum_trades_per_period:
            return EligibilityVerdict(
                reason=EligibilityReason.INSUFFICIENT_TRADING,
                compliance_state=ComplianceState.NON_COMPLIANT,
                balance=check.deposit_total,
            )

    return EligibilityVerdict(
        reason=EligibilityReason.ELIGIBLE,
        compliance_state=ComplianceState.COMPLIANT,
        balance=check.deposit_total,
    )
