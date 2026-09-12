"""Bitunix partner API adapter.

The request shape, the signing scheme and the response fields are all taken
from the working n8n prototype rather than guessed (§38): POST
form-urlencoded ``account`` and ``timestamp`` to
``/partner/api/v2/openapi/validateUser`` with ``apiKey`` and ``signature``
headers, and read registration plus the three deposit buckets back.

Two things the prototype got wrong are deliberately not reproduced:

* it summed deposits with JavaScript ``Number``, i.e. binary floating point,
  on money (§16). Here every amount is a Decimal parsed from its string form.
* its eligibility gate compared against 10 instead of 300 (§26 BUG-03). This
  adapter reports the number and holds no opinion about thresholds at all --
  the minimum lives in ReferralProgramConfig, where an admin sets it.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.application.exceptions import ProviderUnavailableError
from app.application.ports.referral_provider import ReferralCheck, ReferralProvider
from app.domain.enums import ProviderType

BITUNIX_BASE_URL = "https://partners.bitunix.com"
VALIDATE_USER_PATH = "/partner/api/v2/openapi/validateUser"

#: The response splits funding across three rails; eligibility uses the sum.
DEPOSIT_FIELDS = (
    "deposit_usdt_Onchain",
    "deposit_usdt_Internal",
    "deposit_usdt_OTC",
)


@dataclass(frozen=True)
class BitunixCredentials:
    api_key: str
    api_secret: str


def _param_type(key: str) -> int:
    """Bitunix orders keys by character class before ordering within it."""
    first = key[0]
    if first.isdigit():
        return 1
    if first.islower():
        return 2
    return 3


def sign(params: dict[str, Any], api_secret: str) -> str:
    """Reproduce Bitunix's signature exactly.

    Keys are sorted by (character class, sum of character codes) -- not
    lexicographically, which is the detail that makes this worth its own
    tested function. The values are then concatenated in that order, the secret
    is appended, and the whole thing is SHA-1'd.

    SHA-1 is Bitunix's choice, not ours; it is used here only to match their
    verifier, never to protect anything of our own.
    """
    ordered = sorted(params, key=lambda k: (_param_type(k), sum(ord(c) for c in k)))
    concatenated = "".join(str(params[k]) for k in ordered)
    return hashlib.sha1((concatenated + api_secret).encode()).hexdigest()


def _to_decimal(value: Any) -> Decimal:
    """Parse money without ever passing through float."""
    if value is None or value == "":
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)


class BitunixReferralProvider(ReferralProvider):
    provider_type = ProviderType.BITUNIX

    def __init__(
        self,
        credentials: BitunixCredentials,
        client: httpx.AsyncClient | None = None,
        base_url: str = BITUNIX_BASE_URL,
        timeout: float = 15.0,
    ) -> None:
        self._credentials = credentials
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def validate_user(self, uid: str) -> ReferralCheck:
        params = {"account": uid, "timestamp": int(time.time())}
        headers = {
            "apiKey": self._credentials.api_key,
            "signature": sign(params, self._credentials.api_secret),
        }

        try:
            if self._client is not None:
                response = await self._client.post(
                    f"{self._base_url}{VALIDATE_USER_PATH}",
                    data=params,
                    headers=headers,
                    timeout=self._timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base_url}{VALIDATE_USER_PATH}",
                        data=params,
                        headers=headers,
                    )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Network failure, timeout, 5xx, unparseable body -- all of them
            # mean "we could not tell", which §22 requires be distinguishable
            # from "the user is not eligible".
            raise ProviderUnavailableError(f"Bitunix validateUser failed: {exc}") from exc

        return self._parse(uid, payload)

    @staticmethod
    def _parse(uid: str, payload: dict[str, Any]) -> ReferralCheck:
        result = payload.get("result") or {}
        if not isinstance(result, dict):
            raise ProviderUnavailableError(
                f"Bitunix validateUser returned an unexpected body: {payload!r}"
            )
        deposit_total = sum(
            (_to_decimal(result.get(field)) for field in DEPOSIT_FIELDS),
            start=Decimal(0),
        )
        return ReferralCheck(
            uid=uid,
            registered=result.get("result") is True,
            deposit_total=deposit_total,
            raw=payload,
        )
