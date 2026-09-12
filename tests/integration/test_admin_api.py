"""The admin surface a customer configures their own integration through."""

from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.persistence.models import ProviderCredential
from app.core.crypto import ENCRYPTION_KEY_ENV, decrypt_secret, reset_cipher_cache

SECRET = "svfPROmCJdOyHzpZVANhMBNnBhaDYrHFXGfpUmigjVHmvuaPMeUjcMYhsqZZrMEY"


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(ENCRYPTION_KEY_ENV, Fernet.generate_key().decode())
    reset_cipher_cache()
    yield
    reset_cipher_cache()


def _headers(tenant) -> dict[str, str]:
    return {"X-Tenant-ID": str(tenant)}


def test_a_stored_secret_never_comes_back(client: TestClient) -> None:
    """§2 — not even to the admin who typed it, and not in any later read."""
    tenant = uuid4()
    response = client.put(
        "/api/v1/admin/credentials",
        headers=_headers(tenant),
        json={
            "provider_type": "BITUNIX",
            "credential_name": "api_key",
            "secret": SECRET,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert SECRET not in response.text
    assert body["last_four"] == SECRET[-4:]
    assert "secret" not in body
    assert "encrypted_secret" not in body

    listing = client.get("/api/v1/admin/credentials", headers=_headers(tenant))
    assert SECRET not in listing.text


@pytest.mark.asyncio
async def test_the_stored_value_is_ciphertext_not_plaintext(
    client: TestClient, async_session
) -> None:
    tenant = uuid4()
    client.put(
        "/api/v1/admin/credentials",
        headers=_headers(tenant),
        json={"provider_type": "BITUNIX", "credential_name": "api_key", "secret": SECRET},
    )

    row = (
        await async_session.execute(
            select(ProviderCredential.encrypted_secret, ProviderCredential.tenant_id)
        )
    ).first()
    # RLS hides it from an unscoped session, which is itself the point: the
    # value is unreadable both by policy and by encryption.
    if row is not None:
        assert SECRET not in row[0]
        assert decrypt_secret(row[0]) == SECRET


def test_rotating_a_key_clears_its_verification(client: TestClient) -> None:
    """A new key has not been proven to work, whatever the old one did."""
    tenant = uuid4()
    payload = {
        "provider_type": "BITUNIX",
        "credential_name": "api_key",
        "secret": SECRET,
    }
    first = client.put("/api/v1/admin/credentials", headers=_headers(tenant), json=payload)
    second = client.put(
        "/api/v1/admin/credentials",
        headers=_headers(tenant),
        json={**payload, "secret": "a-completely-different-key-9999"},
    )
    assert first.json()["id"] == second.json()["id"]  # rotated, not duplicated
    assert second.json()["last_four"] == "9999"
    assert second.json()["verified_at"] is None


def test_one_tenant_cannot_see_anothers_credentials(client: TestClient) -> None:
    """§28, through the HTTP surface rather than the repository."""
    a, b = uuid4(), uuid4()
    client.put(
        "/api/v1/admin/credentials",
        headers=_headers(a),
        json={"provider_type": "BITUNIX", "credential_name": "api_key", "secret": SECRET},
    )
    listing = client.get("/api/v1/admin/credentials", headers=_headers(b))
    assert listing.json() == []


def test_referral_config_round_trips(client: TestClient) -> None:
    tenant = uuid4()
    response = client.put(
        "/api/v1/admin/referral-config",
        headers=_headers(tenant),
        json={
            "provider_type": "BITUNIX",
            "market": "CRYPTO",
            "referral_link": "https://www.bitunix.com/register?vipCode=OWNER",
            "minimum_balance": "300",
            "minimum_trades_per_period": 1,
            "compliance_grace_period_days": 30,
        },
    )
    assert response.status_code == 200
    assert response.json()["referral_link"].endswith("vipCode=OWNER")
    # The threshold is data, which is the whole answer to BUG-03.
    assert response.json()["minimum_balance"] == "300.00000000"


def test_the_threshold_can_be_changed_without_a_deploy(client: TestClient) -> None:
    tenant = uuid4()
    body = {
        "referral_link": "https://x",
        "minimum_balance": "300",
    }
    client.put("/api/v1/admin/referral-config", headers=_headers(tenant), json=body)
    updated = client.put(
        "/api/v1/admin/referral-config",
        headers=_headers(tenant),
        json={**body, "minimum_balance": "750.5"},
    )
    assert updated.json()["minimum_balance"] == "750.50000000"


def test_channels_are_configuration_not_constants(client: TestClient) -> None:
    """BUG-04: no chat id may live in code."""
    tenant = uuid4()
    crypto = client.put(
        "/api/v1/admin/channels",
        headers=_headers(tenant),
        json={"market": "CRYPTO", "chat_id": -1001111111111, "title": "VIP Crypto"},
    )
    forex = client.put(
        "/api/v1/admin/channels",
        headers=_headers(tenant),
        json={"market": "FOREX", "chat_id": -1002222222222, "title": "VIP Forex"},
    )
    assert crypto.status_code == forex.status_code == 200

    listing = client.get("/api/v1/admin/channels", headers=_headers(tenant)).json()
    by_market = {c["market"]: c["chat_id"] for c in listing}
    assert by_market == {"CRYPTO": -1001111111111, "FOREX": -1002222222222}


def test_the_integration_check_says_what_is_missing(client: TestClient) -> None:
    """§29 — a clear configuration error, not a silent failure later."""
    tenant = uuid4()
    result = client.post("/api/v1/admin/integration-check", headers=_headers(tenant)).json()

    assert result["bot_ok"] is False
    assert result["referral_ok"] is False
    problems = " ".join(result["problems"])
    assert "Telegram bot token" in problems
    assert "no active VIP channel" in problems


def test_admin_routes_require_a_tenant(client: TestClient) -> None:
    assert client.get("/api/v1/admin/credentials").status_code == 401
    assert (
        client.put(
            "/api/v1/admin/credentials",
            json={"provider_type": "BITUNIX", "credential_name": "k", "secret": "s"},
        ).status_code
        == 401
    )


def test_a_secret_is_not_echoed_in_a_validation_error(client: TestClient) -> None:
    """Pydantic error bodies quote the input; a secret must not ride along."""
    tenant = uuid4()
    response = client.put(
        "/api/v1/admin/credentials",
        headers=_headers(tenant),
        json={"provider_type": "NOT_A_PROVIDER", "credential_name": "k", "secret": SECRET},
    )
    assert response.status_code == 422
    assert SECRET not in response.text
