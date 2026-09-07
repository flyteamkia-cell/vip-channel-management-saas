from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.web.dependencies import get_tenant_id
from app.core.database import get_db_session
from app.schemas.payment import PaymentIngestRequest, PaymentIngestResponse
from app.services.payment_service import PaymentProcessingService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/payments", response_model=PaymentIngestResponse)
async def ingest_payment_webhook(
    payload: PaymentIngestRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_db_session),
) -> PaymentIngestResponse:
    service = PaymentProcessingService(session)
    return await service.process_payment(tenant_id, payload)
