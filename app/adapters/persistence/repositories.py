from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import PaymentRecordTable


class SQLAlchemyPaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, tenant_id: UUID, entity_id: UUID) -> PaymentRecordTable | None:
        stmt = select(PaymentRecordTable).where(
            PaymentRecordTable.tenant_id == tenant_id,
            PaymentRecordTable.id == entity_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self, tenant_id: UUID, limit: int = 100, offset: int = 0) -> Sequence[PaymentRecordTable]:
        stmt = (
            select(PaymentRecordTable)
            .where(PaymentRecordTable.tenant_id == tenant_id)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def save(self, tenant_id: UUID, record: PaymentRecordTable) -> PaymentRecordTable:
        record.tenant_id = tenant_id
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def delete(self, tenant_id: UUID, entity_id: UUID) -> bool:
        stmt = delete(PaymentRecordTable).where(
            PaymentRecordTable.tenant_id == tenant_id,
            PaymentRecordTable.id == entity_id
        )
        result = await self.session.execute(stmt)
        if isinstance(result, CursorResult):
            return result.rowcount > 0
        return False
