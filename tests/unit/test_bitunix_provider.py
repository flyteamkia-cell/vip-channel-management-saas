"""The Bitunix adapter, proved against the prototype it replaces."""

from decimal import Decimal

import httpx
import pytest

from app.adapters.providers.bitunix import (
    BitunixCredentials,
    BitunixReferralProvider,
    sign,
)
from app.application.exceptions import ProviderUnavailableError

# Produced by running the n8n workflow's own JavaScript signer (SHA-1 plus its
# unusual key ordering) over these inputs. They are golden vectors: if the
# Python signature ever stops matching them, it has stopped matching Bitunix.
SIGNATURE_VECTORS = [
    ({"account": "123456789", "timestamp": 1700000000}, "af9cc8eb7854b9bb06d18b89f1cec76638139581"),
    ({"account": "000000001", "timestamp": 1}, "51fb438c8a8e9289ebb41777949d1a7c822e7f43"),
    ({"account": "987654321", "timestamp": 1788000000}, "4e4cb26898258517a7965542e83ae533514ee62c"),
]


@pytest.mark.parametrize(("params", "expected"), SIGNATURE_VECTORS)
def test_signature_matches_the_reference_implementation(params, expected) -> None:
    assert sign(params, "SECRET") == expected


def test_key_ordering_is_by_character_class_then_code_sum() -> None:
    """Not lexicographic -- which is the trap this scheme sets.

    'timestamp' sorts before 'account' under Bitunix's rule because its
    character codes sum lower, so a lexicographic signer would produce a valid
    looking hash that the exchange rejects.
    """
    assert sign({"account": "A", "timestamp": "B"}, "s") == sign(
        {"timestamp": "B", "account": "A"}, "s"
    )
    assert sign({"account": "A", "timestamp": "B"}, "s") != sign(
        {"account": "B", "timestamp": "A"}, "s"
    )


def _provider(handler) -> BitunixReferralProvider:
    return BitunixReferralProvider(
        credentials=BitunixCredentials(api_key="k", api_secret="s"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_deposits_are_summed_as_exact_decimals() -> None:
    """The prototype added these with JavaScript Number. §16 forbids that."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "result": True,
                    "deposit_usdt_Onchain": "100.10",
                    "deposit_usdt_Internal": "0.20",
                    "deposit_usdt_OTC": "0.30",
                }
            },
        )

    check = await _provider(handler).validate_user("123456789")
    assert check.registered is True
    # 100.10 + 0.20 + 0.30 is 100.60 exactly. In binary floating point it is
    # 100.60000000000001, and a threshold comparison would eventually disagree
    # with the exchange's own statement.
    assert check.deposit_total == Decimal("100.60")
    assert isinstance(check.deposit_total, Decimal)


@pytest.mark.asyncio
async def test_an_account_outside_our_referral_tree_is_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"result": False}})

    check = await _provider(handler).validate_user("123456789")
    assert check.registered is False
    assert check.deposit_total == Decimal(0)


@pytest.mark.asyncio
async def test_request_carries_the_signed_headers_and_form_body() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content.decode()
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"result": {"result": True}})

    await _provider(handler).validate_user("123456789")

    assert seen["url"].endswith("/partner/api/v2/openapi/validateUser")
    assert seen["headers"]["apikey"] == "k"  # type: ignore[index]
    assert len(seen["headers"]["signature"]) == 40  # type: ignore[index]
    assert "account=123456789" in seen["body"]  # type: ignore[operator]
    assert "timestamp=" in seen["body"]  # type: ignore[operator]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    [
        pytest.param(
            lambda request: (_ for _ in ()).throw(httpx.ConnectTimeout("timed out")),
            id="timeout",
        ),
        pytest.param(lambda request: httpx.Response(503), id="503"),
        pytest.param(lambda request: httpx.Response(200, text="<html>nope"), id="not-json"),
        pytest.param(lambda request: httpx.Response(200, json={"result": "nope"}), id="bad-shape"),
    ],
)
async def test_an_unreachable_provider_is_never_mistaken_for_an_ineligible_user(
    handler,
) -> None:
    """§22: an outage must not read as user inactivity.

    Every one of these has to surface as ProviderUnavailableError so the caller
    can record PROVIDER_UNAVAILABLE and leave the member's standing verdict
    alone, instead of seeing a quiet `registered=False` and revoking them.
    """
    with pytest.raises(ProviderUnavailableError):
        await _provider(handler).validate_user("123456789")
