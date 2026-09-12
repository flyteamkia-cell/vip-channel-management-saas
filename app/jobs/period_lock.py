"""Claiming a scheduled period, exactly once across every instance (§32).

The lock is a row. Two instances waking on the same cron both insert the same
(tenant, job, period) key; the database lets one through and raises on the
other, which stands down. That is simpler and safer than a lease in Redis: no
TTL to tune, no clock skew, no split brain if a process pauses — the database
already serialises writes, so it is the natural arbiter.

Because the key includes the period rather than a timestamp, the claim is also
an idempotency record. Re-running last week's job, by hand or after a redeploy,
finds the period already claimed and does nothing, which is what keeps §32's
"must not send duplicate messages" true.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import JobExecution, utcnow
from app.domain.enums import JobRunState


def period_start_for(now: datetime, period: timedelta) -> datetime:
    """Floor `now` to a stable period boundary.

    Derived from the epoch rather than from "when the job happened to run", so
    every instance computes the same boundary for the same wall clock and two
    of them cannot claim adjacent-but-different periods for the same week.
    """
    moment = now if now.tzinfo else now.replace(tzinfo=UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    elapsed = moment - epoch
    return epoch + timedelta(seconds=(elapsed.total_seconds() // period.total_seconds())
                             * period.total_seconds())


async def claim_period(
    session: AsyncSession,
    tenant_id: UUID,
    job_name: str,
    period_start: datetime,
) -> JobExecution | None:
    """Take ownership of one period, or return None if someone already has it.

    The insert runs inside a SAVEPOINT so that losing the race rolls back only
    the claim attempt. Without it the IntegrityError would poison the caller's
    whole transaction, and the instance that lost a harmless race would also
    lose any work it had already done.
    """
    execution = JobExecution(
        tenant_id=tenant_id,
        job_name=job_name,
        period_start=period_start,
        state=JobRunState.RUNNING,
        started_at=utcnow(),
    )
    try:
        async with session.begin_nested():
            session.add(execution)
            await session.flush()
    except IntegrityError:
        return None
    return execution


def finish(execution: JobExecution, *, error: str | None = None) -> None:
    execution.state = JobRunState.FAILED if error else JobRunState.SUCCEEDED
    execution.finished_at = utcnow()
    execution.error = error[:1000] if error else None
