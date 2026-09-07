"""Shared pytest fixtures for the whole suite.

Design notes
------------
1. Every test module builds its *own* FastAPI instance through ``create_app()``.
   A dependency override installed on ``app.main.app`` at import time therefore
   never reaches those instances. Overrides are installed per-instance in the
   ``client`` fixture below, which is the only place that knows about the app
   under test.

2. ``TestClient`` must be entered as a context manager. Starlette only runs the
   ``lifespan`` handler between ``__enter__`` and ``__exit__``; a bare
   ``TestClient(app)`` skips startup entirely, so any schema bootstrap that
   lives in ``lifespan`` silently never happens.

3. The test database is a *file-backed* SQLite DB in a temp directory rather
   than ``:memory:``. ``TestClient`` drives the ASGI app on its own event loop
   while async fixtures run on pytest-asyncio's loop. An in-memory SQLite
   database only exists inside a single connection, so sharing it across loops
   needs ``StaticPool`` tricks that break the moment a second loop touches the
   connection. A file is visible to every connection on every loop for free,
   and it disappears with the temp directory at the end of the session.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.adapters.persistence.models import Base
from app.core import database as db_module
from app.core.database import get_db_session
from app.main import create_app

_TMP_DIR = tempfile.TemporaryDirectory(prefix="vip-saas-tests-", ignore_cleanup_errors=True)
_DB_FILE = Path(_TMP_DIR.name) / "test.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{_DB_FILE.as_posix()}"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    future=True,
    poolclass=NullPool,  # no connection is held across event loops
)
TestingSessionFactory = async_sessionmaker(
    test_engine, expire_on_commit=False, class_=AsyncSession
)

# Redirect the production engine/session factory at the test database so that
# anything resolving them lazily through the module (the lifespan handler, the
# real ``get_db_session``) can never touch ./test.db during a test run.
db_module.engine = test_engine
db_module.AsyncSessionFactory = TestingSessionFactory


@pytest.fixture(scope="session", autouse=True)
def database_schema() -> Generator[None, None, None]:
    """Create every table declared on ``Base`` once per test session."""

    async def _create() -> None:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    yield
    asyncio.run(test_engine.dispose())
    _TMP_DIR.cleanup()


async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Test replacement for ``app.core.database.get_db_session``."""
    async with TestingSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture
def app_instance() -> Generator[FastAPI, None, None]:
    """A fresh FastAPI app wired to the test database."""
    application = create_app()
    application.dependency_overrides[get_db_session] = override_get_db_session
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app_instance: FastAPI) -> Generator[TestClient, None, None]:
    """HTTP client bound to the test app, with lifespan actually executed."""
    with TestClient(app_instance) as test_client:
        yield test_client
