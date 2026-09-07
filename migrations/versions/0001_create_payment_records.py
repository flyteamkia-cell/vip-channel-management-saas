"""create payment_records

Initial schema. Mirrors app.adapters.persistence.models.PaymentRecordTable.

Revision ID: 0001
Revises: 
Create Date: 2026-09-07 12:42:48.008980

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('payment_records',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('tx_hash', sa.String(length=255), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_payment_records_tenant_id'), 'payment_records', ['tenant_id'], unique=False)
    op.create_index('ix_payments_tenant_id_id', 'payment_records', ['tenant_id', 'id'], unique=False)
    op.create_index('ix_payments_tenant_user', 'payment_records', ['tenant_id', 'user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_payments_tenant_user', table_name='payment_records')
    op.drop_index('ix_payments_tenant_id_id', table_name='payment_records')
    op.drop_index(op.f('ix_payment_records_tenant_id'), table_name='payment_records')
    op.drop_table('payment_records')
