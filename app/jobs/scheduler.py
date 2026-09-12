"""Running the management rules on their own (PHASE0 §31, §32).

APScheduler triggers the pass; the pass itself decides nothing about
concurrency, because the period claim already does (see period_lock). That
split is deliberate: schedulers are approximate — they fire late after a pause,
twice across a redeploy, and once per instance behind a load balancer — so the
correctness of "once per period" must not depend on them.

One tenant at a time, each in its own session and its own transaction. A tenant
whose exchange credentials are missing or whose provider is down must not stop
the sweep for everyone else, so failures are contained per tenant and recorded
on that tenant's own job row.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.adapters.persistence.models import Tenant
from app.application.exceptions import ProviderUnavailableError
from app.core import database
from app.core.tenant_scope import bind_tenant
from app.domain.enums import Market, ProviderType
from app.jobs.membership_monitor import MembershipMonitor
from app.services.provider_factory import MissingCredentialError, ProviderFactory

logger = logging.getLogger("vip_saas.scheduler")

#: How often the sweep runs. The compliance rules space warnings themselves
#: (§24), so running more often than the warning interval is harmless and makes
#: recovery visible sooner.
DEFAULT_SWEEP_INTERVAL = timedelta(hours=24)

#: The window each run accounts for. Must match the trading rule's period (§7).
DEFAULT_COMPLIANCE_PERIOD = timedelta(days=7)


async def active_tenant_ids() -> Sequence[UUID]:
    """Read the registry outside any tenant context — it is not row-scoped."""
    async with database.AsyncSessionFactory() as session:
        rows = await session.execute(select(Tenant.id).where(Tenant.is_active.is_(True)))
        return list(rows.scalars().all())


async def run_compliance_sweep(
    *,
    market: Market = Market.CRYPTO,
    provider_type: ProviderType = ProviderType.BITUNIX,
    period: timedelta = DEFAULT_COMPLIANCE_PERIOD,
) -> None:
    for tenant_id in await active_tenant_ids():
        async with database.AsyncSessionFactory() as session:
            bind_tenant(session, tenant_id)
            factory = ProviderFactory(session)
            try:
                referral = await factory.referral_provider(tenant_id, provider_type)
                telegram = await factory.telegram(tenant_id)
            except MissingCredentialError as exc:
                # Not an outage: this customer has not finished setting up.
                # Nothing to retry, nothing to alert on, and no reason to stop
                # the sweep for everyone else.
                logger.info("skipping tenant %s: %s", tenant_id, exc)
                continue

            monitor = MembershipMonitor(session, referral, telegram, period=period)
            try:
                report = await monitor.run(tenant_id)
                await session.commit()
            except ProviderUnavailableError as exc:
                await session.rollback()
                logger.warning("tenant %s: provider unavailable: %s", tenant_id, exc)
                continue
            except Exception:
                await session.rollback()
                logger.exception("tenant %s: compliance sweep failed", tenant_id)
                continue

            if report.claimed:
                logger.info(
                    "tenant %s: processed=%d warned=%d revoked=%d restored=%d unavailable=%d",
                    tenant_id,
                    report.processed,
                    report.warned,
                    report.revoked,
                    report.restored,
                    report.skipped_unavailable,
                )


def build_scheduler(interval: timedelta = DEFAULT_SWEEP_INTERVAL) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_compliance_sweep,
        IntervalTrigger(seconds=int(interval.total_seconds())),
        id="referral_compliance_sweep",
        # If a run is missed — the process was down, or the previous one ran
        # long — collapse the backlog into one. The period claim would reject
        # the duplicates anyway; this just avoids queueing work that cannot run.
        coalesce=True,
        max_instances=1,
        misfire_grace_time=int(timedelta(hours=1).total_seconds()),
    )
    return scheduler
