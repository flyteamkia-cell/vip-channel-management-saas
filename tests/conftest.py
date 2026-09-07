"""Shared pytest fixtures for the whole suite.

Test database strategy
----------------------
Two backends, chosen by the layer under test:

* ``tests/unit`` runs on a throwaway **SQLite** file — no external service, so
  the fast feedback loop stays fast.
* ``tests/integration`` and ``tests/e2e`` run on **PostgreSQL**, because that is
  what production uses. SQLite silently accepts things Postgres rejects (native
  ``uuid``/``numeric``/``timestamptz`` semantics, transaction and locking
  behaviour, index rules), so an e2e test on SQLite is really testing a
  different application. The marker is applied automatically by directory in
  ``pytest_collection_modifyitems`` below; ``@pytest.mark.postgres`` can also be
  set by hand.

Point ``TEST_DATABASE_URL`` at a disposable database, e.g.::

    docker compose -f docker-compose.test.yml up -d
    export TEST_DATABASE_URL="postgresql+asyncpg://vip:vip@localhost:5433/vip_test"
    pytest

Without that variable the Postgres-backed tests are **skipped** rather than
quietly downgraded to SQLite. Set ``TEST_REQUIRE_POSTGRES=1`` (do this in CI) to
turn that skip into a hard failure, so the layer can never silently stop running.

Schema is always built by ``alembic upgrade head`` — never ``create_all``. Any
drift between the models and the migrations therefore shows up as a failing
test instead of surfacing on the first production deploy.

Two mechanics worth remembering
-------------------------------
1. Every test module builds its own FastAPI instance via ``create_app()``, so a
   dependency override installed on ``app.main.app`` at import time never
   reaches it. Overrides are installed per-instance in the ``client`` fixture.
2. ``TestClient`` must be entered as a context manager; Starlette only runs the
   ``lifespan`` handler between ``__enter__`` and ``__exit__``.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator, Generator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.adapters.persistence.models import Base
from app.core import database as db_module
from app.core.tenant_scope import bind_tenant
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSTGRES_URL_ENV = "TEST_DATABASE_URL"
REQUIRE_POSTGRES_ENV = "TEST_REQUIRE_POSTGRES"

_POSTGRES_MISSING = (
    f"{POSTGRES_URL_ENV} is not set — integration/e2e tests need a real "
    "PostgreSQL database. Start one with "
    "`docker compose -f docker-compose.test.yml up -d` and export the URL."
)


# --------------------------------------------------------------------------- #
# collection: pick the backend by layer
# --------------------------------------------------------------------------- #
def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "postgres: test requires a real PostgreSQL database"
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        parts = Path(str(item.path)).parts
        if "integration" in parts or "e2e" in parts:
            item.add_marker(pytest.mark.postgres)


# --------------------------------------------------------------------------- #
# schema: always via Alembic
# --------------------------------------------------------------------------- #
@contextmanager
def _database_url(url: str) -> Iterator[None]:
    """Expose `url` to migrations/env.py, then restore the previous value."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def _alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return config


def migrate(url: str, revision: str = "head") -> None:
    with _database_url(url):
        command.upgrade(_alembic_config(), revision)


def unmigrate(url: str) -> None:
    with _database_url(url):
        command.downgrade(_alembic_config(), "base")


# --------------------------------------------------------------------------- #
# backends
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Backend:
    url: str
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


def _make_backend(url: str) -> Backend:
    # NullPool: no connection is ever held across event loops. TestClient runs
    # the ASGI app on its own loop while async fixtures run on pytest-asyncio's,
    # and a pooled asyncpg/aiosqlite connection bound to a dead loop is the
    # classic "attached to a different loop" failure.
    engine = create_async_engine(url, echo=False, future=True, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return Backend(url=url, engine=engine, session_factory=factory)


@pytest.fixture(scope="session")
def sqlite_backend() -> Generator[Backend, None, None]:
    with tempfile.TemporaryDirectory(
        prefix="vip-saas-tests-", ignore_cleanup_errors=True
    ) as tmp_dir:
        db_file = Path(tmp_dir) / "test.db"
        url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
        migrate(url)
        backend = _make_backend(url)
        yield backend
        backend.engine.sync_engine.dispose()


@pytest.fixture(scope="session")
def postgres_backend() -> Generator[Backend, None, None]:
    url = os.getenv(POSTGRES_URL_ENV)
    if not url:
        if os.getenv(REQUIRE_POSTGRES_ENV) == "1":
            pytest.fail(_POSTGRES_MISSING, pytrace=False)
        pytest.skip(_POSTGRES_MISSING, allow_module_level=True)

    # Start from a known-empty schema so a leftover database from a previous
    # run cannot make a broken migration look healthy.
    unmigrate(url)
    migrate(url)
    backend = _make_backend(url)
    yield backend
    backend.engine.sync_engine.dispose()
    unmigrate(url)


@pytest.fixture
def backend(request: pytest.FixtureRequest) -> Backend:
    """The database this test should run against."""
    if request.node.get_closest_marker("postgres"):
        return request.getfixturevalue("postgres_backend")
    return request.getfixturevalue("sqlite_backend")


@pytest.fixture(autouse=True)
async def clean_tables(backend: Backend) -> AsyncGenerator[None, None]:
    """Leave the database empty for the next test.

    The web layer commits, so rolling a transaction back is not enough here.

    On PostgreSQL this must be TRUNCATE, not DELETE: row-level security is
    forced on the tenant-scoped tables, and a DELETE issued with no tenant
    published matches no rows and quietly cleans nothing. TRUNCATE is a
    table-level operation and is not subject to row policies.
    """
    yield
    tables = list(reversed(Base.metadata.sorted_tables))
    async with backend.engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            names = ", ".join(f'"{t.name}"' for t in tables)
            await conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        else:
            for table in tables:
                await conn.execute(text(f'DELETE FROM "{table.name}"'))


@pytest.fixture
async def rls_enforced(backend: Backend) -> bool:
    """Whether the connection is actually subject to row-level security.

    PostgreSQL exempts superusers and BYPASSRLS roles from row policies, so a
    suite run as `postgres` would pass the isolation tests without ever
    evaluating one. Tests that assert on RLS skip loudly rather than pass
    vacuously.
    """
    if backend.engine.dialect.name != "postgresql":
        pytest.skip("row-level security is a PostgreSQL feature")
    async with backend.engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles "
                "WHERE rolname = current_user"
            )
        )
        if row.scalar():
            pytest.skip(
                "connected as a superuser or BYPASSRLS role, which PostgreSQL "
                "exempts from row policies -- run as an ordinary role to "
                "exercise row-level security"
            )
    return True


@pytest.fixture
def tenant_session(backend: Backend):
    """Factory for sessions scoped to a given tenant.

    Mirrors production: one session belongs to one tenant for its lifetime,
    which is what makes the RLS setting and the loader criteria meaningful.
    """

    @asynccontextmanager
    async def _factory(tenant_id: UUID) -> AsyncGenerator[AsyncSession, None]:
        async with backend.session_factory() as session:
            bind_tenant(session, tenant_id)
            yield session

    return _factory


# --------------------------------------------------------------------------- #
# application wiring
# --------------------------------------------------------------------------- #
@pytest.fixture
def app_instance(backend: Backend) -> Generator[FastAPI, None, None]:
    # get_tenant_session resolves the factory through the module, so redirecting
    # it here is the whole wiring: no dependency override, and nothing that
    # resolves the engine lazily (the lifespan handler, get_db_session) can
    # reach the developer's own database during a test run.
    original_engine, original_factory = db_module.engine, db_module.AsyncSessionFactory
    db_module.engine = backend.engine
    db_module.AsyncSessionFactory = backend.session_factory

    application = create_app()
    yield application
    application.dependency_overrides.clear()

    db_module.engine, db_module.AsyncSessionFactory = original_engine, original_factory


@pytest.fixture
def client(app_instance: FastAPI) -> Generator[TestClient, None, None]:
    """HTTP client bound to the test database, with lifespan actually executed."""
    with TestClient(app_instance) as test_client:
        yield test_client


@pytest.fixture
async def async_session(backend: Backend) -> AsyncGenerator[AsyncSession, None]:
    """Unscoped session -- no tenant bound.

    Useful for asserting what an unscoped caller can see, which under RLS is
    nothing. Tests that act on behalf of a tenant should use ``tenant_session``.
    """
    async with backend.session_factory() as session:
        yield session
