from uuid import UUID

from fastapi import Request


def get_tenant_id(request: Request) -> UUID:
    """The tenant resolved by :class:`TenantContextMiddleware`.

    Presence is a structural guarantee, not a runtime check: the middleware has
    either set it or already returned 401/400. If it is missing, the route was
    mounted outside the middleware's reach — a wiring bug that must surface as a
    500, never as a request quietly processed without a tenant.
    """
    tenant_id: UUID | None = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise RuntimeError(
            f"No tenant context for {request.url.path}. Either TenantContextMiddleware "
            "is not registered, or this path is listed in its public_paths."
        )
    return tenant_id
