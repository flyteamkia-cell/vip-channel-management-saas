from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Numeric, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TenantScoped:
    """Marker for tables that belong to exactly one tenant.

    Two mechanisms key off this class, so a new table gets both by inheriting
    it: ``with_loader_criteria`` filters every ORM SELECT (see
    ``app.core.tenant_scope``), and the RLS migration enables a row policy on
    the table. Declaring ``tenant_id`` here rather than per model keeps the two
    from drifting apart.
    """

    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)


class PaymentRecordTable(TenantScoped, Base):
    __tablename__ = "payment_records"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USDT", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False
    )

    __table_args__ = (
        Index("ix_payments_tenant_id_id", "tenant_id", "id"),
        Index("ix_payments_tenant_user", "tenant_id", "user_id"),
    )
