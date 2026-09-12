"""Guards that keep the schema and its protections from drifting apart."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence import models
from app.adapters.persistence.models import Base, TenantScoped


def _tenant_scoped_tables() -> set[str]:
    return {
        cls.__tablename__
        for name in models.__all__
        if isinstance(cls := getattr(models, name), type)
        and issubclass(cls, TenantScoped)
        and hasattr(cls, "__tablename__")
    }


@pytest.mark.asyncio
async def test_every_tenant_scoped_table_has_a_forced_row_policy(
    async_session: AsyncSession, rls_enforced: bool
) -> None:
    """A new model that inherits TenantScoped must also get an RLS migration.

    The ORM half of the protection comes for free with the mixin, so a table
    added without the migration half looks correct in every ORM test and is
    wide open to raw SQL. This test is the thing that notices.
    """
    rows = (
        await async_session.execute(
            text(
                """
                SELECT c.relname,
                       c.relrowsecurity,
                       c.relforcerowsecurity,
                       count(p.polname) AS policies
                FROM pg_class c
                LEFT JOIN pg_policy p ON p.polrelid = c.oid
                WHERE c.relkind = 'r'
                  AND c.relnamespace = 'public'::regnamespace
                GROUP BY 1, 2, 3
                """
            )
        )
    ).all()
    state = {r[0]: (r[1], r[2], r[3]) for r in rows}

    unprotected = [
        table
        for table in sorted(_tenant_scoped_tables())
        if state.get(table, (False, False, 0)) != (True, True, 1)
    ]
    assert not unprotected, (
        f"tenant-scoped tables without a forced row policy: {unprotected}. "
        "Add them to the RLS block of the newest Alembic revision."
    )


@pytest.mark.asyncio
async def test_tenants_table_is_not_row_scoped(
    async_session: AsyncSession, rls_enforced: bool
) -> None:
    """The tenant registry must stay reachable without a tenant context.

    A row policy on `tenants` keyed to the current tenant would make creating
    the very first tenant impossible: the WITH CHECK cannot pass before the
    tenant exists. Guarding it here so nobody 'fixes' the apparent omission.
    """
    enabled = (
        await async_session.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE relname = 'tenants'")
        )
    ).scalar()
    assert enabled is False


def test_every_model_is_exported_from_the_package() -> None:
    """A model missing from models/__init__ is invisible to Alembic and tests.

    That is the exact shape of the "no such table" failure this project opened
    with, so it is worth a test that needs no database.
    """
    exported = {
        cls.__tablename__
        for name in models.__all__
        if isinstance(cls := getattr(models, name), type) and hasattr(cls, "__tablename__")
    }
    assert exported == set(Base.metadata.tables)
