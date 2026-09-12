"""job executions: the once-per-period claim that serialises scheduled work

The unique key (tenant_id, job_name, period_start) is the distributed lock
required by PHASE0 §32. Two instances waking on the same cron both insert; the
database lets one through. Because the key names the period rather than the
moment, the row doubles as an idempotency record, so a replayed run does
nothing instead of warning everyone a second time.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-12 11:29:28.548476

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PREDICATE = "tenant_id = NULLIF(current_setting(\'app.tenant_id\', true), \'\')::uuid"


def upgrade() -> None:
    op.create_table('job_executions',
    sa.Column('job_name', sa.String(length=100), nullable=False),
    sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('state', sa.Enum('RUNNING', 'SUCCEEDED', 'FAILED', name='jobrunstate', native_enum=False, length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('processed', sa.Integer(), nullable=False),
    sa.Column('warned', sa.Integer(), nullable=False),
    sa.Column('revoked', sa.Integer(), nullable=False),
    sa.Column('skipped_unavailable', sa.Integer(), nullable=False),
    sa.Column('error', sa.String(length=1000), nullable=True),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'job_name', 'period_start', name='uq_job_executions_tenant_job_period')
    )
    op.create_index(op.f('ix_job_executions_tenant_id'), 'job_executions', ['tenant_id'], unique=False)


    if op.get_context().dialect.name == "postgresql":
        op.execute("ALTER TABLE job_executions ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE job_executions FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON job_executions "
            f"USING ({PREDICATE}) WITH CHECK ({PREDICATE})"
        )


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON job_executions")
        op.execute("ALTER TABLE job_executions NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE job_executions DISABLE ROW LEVEL SECURITY")

    op.drop_index(op.f('ix_job_executions_tenant_id'), table_name='job_executions')
    op.drop_table('job_executions')
