from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.web.middlewares.tenant_context import TenantContextMiddleware
from app.adapters.web.routers.health import router as health_router
from app.adapters.web.routers.webhooks import router as webhooks_router
from app.core import database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup/shutdown.

    Schema creation deliberately does NOT happen here. Alembic owns the schema
    (`alembic upgrade head`); a `create_all` on startup would be a second,
    competing source of truth that silently papers over migrations that were
    never written — and it would hide exactly that drift in the test suite,
    which now builds its schema from the migrations themselves.

    The engine is reached through the module rather than imported by value so
    that tests can substitute `database.engine` before the app starts.
    """
    yield
    await database.engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="VIP Channel Management SaaS",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Tenant resolution happens once, before routing. Handlers read the result
    # from request.state via the get_tenant_id dependency.
    application.add_middleware(TenantContextMiddleware)

    application.include_router(health_router)
    # اضافه کردن پیشوند /api/v1
    application.include_router(webhooks_router, prefix="/api/v1")

    return application


app = create_app()
