from decimal import Decimal
from uuid import UUID

from sqlalchemy import Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.persistence.models.base import Base, TenantScoped, TimestampedEntity


class PaymentRecordTable(TenantScoped, TimestampedEntity, Base):
    """Money received (PHASE0 §11). Not an entitlement, not a membership.

    Stage 1 (referral) does not write here at all — §13 says a referral user
    may become eligible without ever paying us, so they must not be pushed
    through the payment subsystem. Stage 2 fills this in.

    `amount` is Numeric(30, 8), widened from the original (12, 2). §11 lists
    Network and Asset alongside Amount, so the values arriving here are crypto:
    USDT carries 6 decimal places and BTC 8, and two would have rounded a real
    transfer to zero without raising anything. That is precisely the failure
    §16 exists to prevent.
    """

    __tablename__ = "payment_records"
    __table_args__ = (
        Index("ix_payments_tenant_id_id", "tenant_id", "id"),
        Index("ix_payments_tenant_user", "tenant_id", "user_id"),
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 8), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USDT", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="PENDING", nullable=False)
