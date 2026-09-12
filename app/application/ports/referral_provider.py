"""Contract for an exchange/broker referral programme (PHASE0 §37 E).

Business logic depends on this, never on Bitunix. §38 is the reason: where an
external API is unclear you implement the interface and a mock, prove the rules
against the mock, and attach the real provider afterwards. It also means adding
eplanet, or any future exchange, touches one adapter and nothing else.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.domain.enums import ProviderType


@dataclass(frozen=True)
class ReferralCheck:
    """What a provider can tell us about one UID, right now.

    `registered` answers "is this account under our referral?" and
    `deposit_total` answers "how much has it funded?". They are separate
    because the eligibility rule combines them and the failure messages differ:
    "we cannot find you under our link" is a different problem for the user
    than "your balance is below the minimum".
    """

    uid: str
    registered: bool
    deposit_total: Decimal = Decimal(0)
    qualifying_trades: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class ReferralProvider(ABC):
    """One exchange's view of our referral tree."""

    provider_type: ProviderType

    @abstractmethod
    async def validate_user(self, uid: str) -> ReferralCheck:
        """Look the UID up.

        Returns a ReferralCheck for any answer the provider actually gave,
        including "not one of ours" (``registered=False``).

        Raises ProviderUnavailableError when the provider could not be reached
        or answered with something unusable. That distinction is the whole of
        §22: an outage must never be recorded as user inactivity, so the code
        that calls this has to see a different signal for "the user is not
        eligible" and "we could not tell".
        """
