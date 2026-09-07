from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import database
from app.core.tenant_scope import bind_tenant


def get_tenant_id(request: Request) -> UUID:
    """The tenant resolved by :class:`TenantContextMiddleware`.

    Presence is a structural guarantee, not a runtime check: the middleware has
    either set it or already returned 401/400. If it is missing, the route was
    mounted outside the middleware's reach -- a wiring bug that must surface as a
    500, never as a request quietly processed without a tenant.
    """
    tenant_id: UUID | None = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise RuntimeError(
            f"No tenant context for {request.url.path}. Either TenantContextMiddleware "
            "is not registered, or this path is listed in its public_paths."
        )
    return tenant_id


async def get_tenant_session(
    tenant_id: UUID = Depends(get_tenant_id),
) -> AsyncGenerator[AsyncSession, None]:
    """A session scoped to the caller's tenant for its whole lifetime.

    This is the single place tenant scoping is established. Everything below --
    services, repositories, hand-written queries -- inherits it without being
    told, through the loader criteria and the PostgreSQL row policy described in
    ``app.core.tenant_scope``.

    The session factory is reached through the module so that tests can
    substitute it.
    """
    async with database.AsyncSessionFactory() as session:
        bind_tenant(session, tenant_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
