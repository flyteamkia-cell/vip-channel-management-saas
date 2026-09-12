from collections.abc import Awaitable, Callable, Iterable
from uuid import UUID

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

#: Routes served without a tenant context.
DEFAULT_PUBLIC_PATHS: frozenset[str] = frozenset(
    {"/health", "/docs", "/redoc", "/openapi.json"}
)


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Resolve and validate the tenant for every non-public request.

    This runs before routing, which is the point: an unauthenticated request is
    rejected before FastAPI validates the body, before dependencies resolve and
    before a database session is ever opened. Handlers downstream can therefore
    treat ``request.state.tenant_id`` as a guaranteed, already-validated UUID
    instead of re-deriving it — one place decides who the caller is.
    """

    def __init__(
        self,
        app: ASGIApp,
        public_paths: Iterable[str] | None = None,
        public_prefixes: Iterable[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.public_paths = frozenset(public_paths) if public_paths else DEFAULT_PUBLIC_PATHS
        # Prefixes exist for callers that cannot send a header at all -- the
        # Telegram webhook identifies its tenant by an unguessable path token,
        # because Telegram has no idea which of our customers it is calling
        # about. Such a route authenticates itself; it is not unprotected.
        self.public_prefixes = tuple(public_prefixes or ())

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path in self.public_paths or path.startswith(self.public_prefixes):
            return await call_next(request)

        tenant_header = request.headers.get("X-Tenant-ID")
        if not tenant_header:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing mandatory X-Tenant-ID header"},
            )

        try:
            tenant_id = UUID(tenant_header)
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Invalid X-Tenant-ID header format"},
            )

        request.state.tenant_id = tenant_id
        return await call_next(request)
