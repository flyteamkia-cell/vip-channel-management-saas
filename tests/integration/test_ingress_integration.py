from uuid import uuid4

from fastapi.testclient import TestClient


def test_full_webhook_ingest_flow_with_tenant_isolation(client: TestClient) -> None:
    tenant_id = str(uuid4())
    payload = {
        "tx_hash": "0xabcdef1234567890",
        "user_id": str(uuid4()),
        "amount": "250.00",
        "currency": "USDT",
    }

    # 1. Request without X-Tenant-ID should fail at the guard
    unauth_res = client.post("/api/v1/webhooks/payments", json=payload)
    assert unauth_res.status_code == 401

    # 2. Request with valid tenant header should pass through the guard and router
    auth_res = client.post(
        "/api/v1/webhooks/payments",
        headers={"X-Tenant-ID": tenant_id},
        json=payload,
    )
    assert auth_res.status_code == 200
    data = auth_res.json()
    assert data["status"] == "PROCESSED"
    assert "payment_id" in data
