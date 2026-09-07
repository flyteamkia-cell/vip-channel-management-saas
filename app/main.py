from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.adapters.persistence.models import Base
from app.adapters.web.routers.webhooks import router as webhooks_router
from app.core import database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # The engine is resolved through the module (not imported by value) so that
    # tests can substitute ``database.engine`` before the app starts up.
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="VIP Channel Management SaaS",
        version="1.0.0",
        lifespan=lifespan,
    )
    # اضافه کردن پیشوند /api/v1
    application.include_router(webhooks_router, prefix="/api/v1")

    @application.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
