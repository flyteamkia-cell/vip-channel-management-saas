from collections.abc import AsyncGenerator
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.web.dependencies import get_tenant_session

WEBHOOK_URL = "/api/v1/webhooks/payments"


def _valid_payload() -> dict[str, str]:
    return {
        "tx_hash": "0x1234567890abcdef",
        "user_id": str(uuid4()),
        "amount": "100.00",
        "currency": "USDT",
    }


def test_health_check_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_missing_tenant_id_header(client: TestClient) -> None:
    response = client.post(WEBHOOK_URL, json=_valid_payload())
    assert response.status_code == 401
    assert "Missing mandatory X-Tenant-ID header" in response.json()["detail"]


def test_malformed_tenant_id_header(client: TestClient) -> None:
    response = client.post(
        WEBHOOK_URL,
        headers={"X-Tenant-ID": "not-a-uuid"},
        json=_valid_payload(),
    )
    assert response.status_code == 400
    assert "Invalid X-Tenant-ID header format" in response.json()["detail"]


def test_valid_tenant_id_header_payment_ingest(client: TestClient) -> None:
    response = client.post(
        WEBHOOK_URL,
        headers={"X-Tenant-ID": str(uuid4())},
        json=_valid_payload(),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PROCESSED"


def test_tenant_guard_runs_before_body_validation(client: TestClient) -> None:
    """An unauthenticated caller gets 401, never a 422 describing the schema.

    The middleware runs before routing, so a missing tenant is rejected without
    the request body ever being validated. Reversing that order would leak the
    payload contract to callers who have not identified themselves.
    """
    response = client.post(WEBHOOK_URL, json={"garbage": True})
    assert response.status_code == 401


def test_body_validation_still_applies_for_a_known_tenant(client: TestClient) -> None:
    response = client.post(
        WEBHOOK_URL,
        headers={"X-Tenant-ID": str(uuid4())},
        json={"tx_hash": "0xabc", "user_id": str(uuid4()), "amount": "-5"},
    )
    assert response.status_code == 422


def test_rejected_request_never_opens_a_database_session(app_instance: FastAPI) -> None:
    """The guard short-circuits before dependencies resolve.

    Cheap to assert, and it is the difference between an unauthenticated flood
    costing a connection each and costing nothing.
    """
    opened = 0

    async def counting_session() -> AsyncGenerator[None, None]:
        nonlocal opened
        opened += 1
        yield None

    app_instance.dependency_overrides[get_tenant_session] = counting_session

    with TestClient(app_instance) as test_client:
        assert test_client.post(WEBHOOK_URL, json=_valid_payload()).status_code == 401

    assert opened == 0
