from uuid import uuid4

from fastapi.testclient import TestClient


def test_health_check_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_missing_tenant_id_header(client: TestClient) -> None:
    response = client.post(
        "/api/v1/webhooks/payments",
        json={
            "tx_hash": "0x1234567890abcdef",
            "user_id": str(uuid4()),
            "amount": "100.00",
            "currency": "USDT",
        },
    )
    assert response.status_code == 401
    assert "Missing mandatory X-Tenant-ID header" in response.json()["detail"]


def test_valid_tenant_id_header_payment_ingest(client: TestClient) -> None:
    tenant_id = str(uuid4())
    response = client.post(
        "/api/v1/webhooks/payments",
        headers={"X-Tenant-ID": tenant_id},
        json={
            "tx_hash": "0x1234567890abcdef",
            "user_id": str(uuid4()),
            "amount": "100.00",
            "currency": "USDT",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PROCESSED"
