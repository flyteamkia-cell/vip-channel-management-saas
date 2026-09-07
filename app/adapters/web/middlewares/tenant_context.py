from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if request.url.path in ["/health", "/docs", "/openapi.json", "/redoc"]:
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
