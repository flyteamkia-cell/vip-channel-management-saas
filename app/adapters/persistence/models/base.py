from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


class TenantScoped:
    """Marker for tables that belong to exactly one tenant.

    Two mechanisms key off this class, so a new table gets both by inheriting
    it: ``with_loader_criteria`` filters every ORM SELECT (see
    ``app.core.tenant_scope``), and the RLS migrations enable a row policy on
    the table. Declaring ``tenant_id`` here rather than per model keeps the two
    from drifting apart.

    Adding a table: inherit this, and add its name to TENANT_SCOPED_TABLES in
    the newest RLS migration. The `test_every_tenant_scoped_table_has_a_policy`
    test fails if you forget the second half.
    """

    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)


class TimestampedEntity:
    """Surrogate primary key plus created/updated stamps."""

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
