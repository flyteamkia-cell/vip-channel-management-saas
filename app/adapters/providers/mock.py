"""In-memory referral provider for tests and local development (PHASE0 §38).

Every business rule in stage 1 is proved against this, not against Bitunix, so
the rules can be finished and trusted before anyone has live API keys — and so
the test suite never depends on an exchange being up.

It can also be told to fail, which is how the §22 path gets exercised: an
outage has to leave a member's verdict standing rather than reading as
inactivity, and that is impossible to test against a provider that always
answers.
"""

from __future__ import annotations

from decimal import Decimal

from app.application.exceptions import ProviderUnavailableError
from app.application.ports.referral_provider import ReferralCheck, ReferralProvider
from app.domain.enums import ProviderType


class MockReferralProvider(ReferralProvider):
    def __init__(
        self,
        provider_type: ProviderType = ProviderType.BITUNIX,
        accounts: dict[str, ReferralCheck] | None = None,
        unavailable: bool = False,
    ) -> None:
        self.provider_type = provider_type
        self.accounts = accounts or {}
        self.unavailable = unavailable
        self.calls: list[str] = []

    def register(
        self,
        uid: str,
        deposit_total: Decimal | str | int = 0,
        registered: bool = True,
        qualifying_trades: int | None = None,
    ) -> None:
        self.accounts[uid] = ReferralCheck(
            uid=uid,
            registered=registered,
            deposit_total=Decimal(str(deposit_total)),
            qualifying_trades=qualifying_trades,
        )

    async def validate_user(self, uid: str) -> ReferralCheck:
        self.calls.append(uid)
        if self.unavailable:
            raise ProviderUnavailableError("mock provider is configured as unavailable")
        return self.accounts.get(uid, ReferralCheck(uid=uid, registered=False))
