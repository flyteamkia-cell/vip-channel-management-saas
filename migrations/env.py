"""Alembic environment, async-first.

The application runs on an async driver (asyncpg in production, aiosqlite
locally), so migrations use the same async engine rather than a second, sync
driver. That keeps one connection story for the whole project: whatever URL the
app can open, Alembic can open too.

The URL comes from the ``DATABASE_URL`` environment variable via
``app.core.database``. It is deliberately absent from ``alembic.ini`` so that the
same migration set applies to dev, CI and production untouched.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.adapters.persistence.models import Base
from app.core.database import get_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The URL is deliberately NOT written into the Alembic config. alembic.ini is
# parsed by configparser, whose interpolation treats "%" as an escape, so a URL
# carrying a percent-encoded password (any password with a character that needs
# encoding -- "!" becomes %21, and "%" itself) would raise
# "invalid interpolation syntax" before a single migration ran. Passing the URL
# straight to the engine keeps configparser out of the path entirely.
target_metadata = Base.metadata


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # SQLite cannot ALTER most things in place; batch mode rewrites the
        # table instead. No-op on PostgreSQL.
        render_as_batch=connection.dialect.name == "sqlite",
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live async connection."""
    connectable = create_async_engine(get_database_url(), poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
