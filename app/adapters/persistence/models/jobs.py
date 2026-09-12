from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.persistence.models.base import Base, TenantScoped, TimestampedEntity
from app.domain.enums import JobRunState


class JobExecution(TenantScoped, TimestampedEntity, Base):
    """One scheduled run, claimed exactly once (PHASE0 §32).

    The unique constraint on (tenant_id, job_name, period_start) IS the
    distributed lock. Two application instances waking on the same schedule
    both try to insert the claim row; PostgreSQL lets exactly one succeed and
    the loser sees an integrity error and stands down. No Redis, no lease
    timeout, no clock skew — the database already arbitrates writes, so the
    cheapest correct lock is one it enforces itself.

    The period key is what makes it idempotent rather than merely exclusive: a
    replayed or manually triggered run for a period that already ran is a
    no-op, so nobody is warned twice for the same week (§32: "running the same
    job twice must not send duplicate messages or perform duplicate membership
    actions").
    """

    __tablename__ = "job_executions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "job_name", "period_start", name="uq_job_executions_tenant_job_period"
        ),
    )

    job_name: Mapped[str] = mapped_column(String(100), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[JobRunState] = mapped_column(
        Enum(JobRunState, native_enum=False, length=32),
        nullable=False,
        default=JobRunState.RUNNING,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revoked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_unavailable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
