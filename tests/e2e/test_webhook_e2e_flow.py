from uuid import uuid4

from fastapi.testclient import TestClient


def test_e2e_payment_webhook_lifecycle(client: TestClient) -> None:
    tenant_id = str(uuid4())
    user_id = str(uuid4())

    # 1. Verification of open public route (Health Check)
    health_res = client.get("/health")
    assert health_res.status_code == 200
    assert health_res.json()["status"] == "ok"

    # 2. Rejection due to invalid tenant UUID format
    invalid_header_res = client.post(
        "/api/v1/webhooks/payments",
        headers={"X-Tenant-ID": "invalid-uuid-string"},
        json={
            "tx_hash": "0x1234567890abcdef",
            "user_id": user_id,
            "amount": "100.00",
            "currency": "USDT",
        },
    )
    assert invalid_header_res.status_code == 400
    assert "Invalid X-Tenant-ID header format" in invalid_header_res.json()["detail"]

    # 3. Successful Ingestion End-to-End Flow
    valid_res = client.post(
        "/api/v1/webhooks/payments",
        headers={"X-Tenant-ID": tenant_id},
        json={
            "tx_hash": "0x1234567890abcdef",
            "user_id": user_id,
            "amount": "100.00",
            "currency": "USDT",
        },
    )
    assert valid_res.status_code == 200
    res_data = valid_res.json()
    assert res_data["status"] == "PROCESSED"
    assert "payment_id" in res_data
