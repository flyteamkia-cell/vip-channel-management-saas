from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import PaymentRecordTable
from app.adapters.persistence.repositories import SQLAlchemyPaymentRepository
from app.schemas.payment import PaymentIngestRequest, PaymentIngestResponse


class PaymentProcessingService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = SQLAlchemyPaymentRepository(session)

    async def process_payment(
        self, tenant_id: UUID, payload: PaymentIngestRequest
    ) -> PaymentIngestResponse:
        record = PaymentRecordTable(
            user_id=payload.user_id,
            tx_hash=payload.tx_hash,
            amount=payload.amount,
            currency=payload.currency,
            status="PROCESSED",
        )
        saved_record = await self.repository.save(tenant_id, record)

        return PaymentIngestResponse(
            status=saved_record.status,
            payment_id=saved_record.id,
            tx_hash=saved_record.tx_hash,
        )
