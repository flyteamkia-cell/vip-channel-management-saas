from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db_session
from app.schemas.payment import PaymentIngestRequest, PaymentIngestResponse
from app.services.payment_service import PaymentProcessingService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/payments", response_model=PaymentIngestResponse)
async def ingest_payment_webhook(
    payload: PaymentIngestRequest,
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    session: AsyncSession = Depends(get_db_session),
) -> PaymentIngestResponse:
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing mandatory X-Tenant-ID header",
        )

    try:
        tenant_uuid = UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid X-Tenant-ID header format",
        )

    service = PaymentProcessingService(session)
    return await service.process_payment(tenant_uuid, payload)
