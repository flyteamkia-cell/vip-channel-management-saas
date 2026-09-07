"""enable row-level security on tenant-scoped tables

Defence in depth for multi-tenancy: the predicate lives in the database, so it
still applies when the ORM is bypassed -- raw SQL, a Core delete(), a report
query someone writes by hand.

FORCE ROW LEVEL SECURITY matters as much as ENABLE: without it the table owner
is exempt, and in most deployments the application connects as the owner.
PostgreSQL still exempts superusers and BYPASSRLS roles entirely, so the
application role must be an ordinary one.

The policy fails closed. current_setting(..., missing_ok => true) returns NULL
when no tenant has been published for the transaction; `tenant_id = NULL` is
NULL, so no row matches and a read returns nothing rather than everything.

SQLite has no row-level security, so this revision is a no-op there. The unit
layer keeps its ORM-level scoping via with_loader_criteria; only the Postgres
layers exercise the policy.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-07

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("payment_records",)

PREDICATE = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table in TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({PREDICATE}) WITH CHECK ({PREDICATE})"
        )


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table in TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
