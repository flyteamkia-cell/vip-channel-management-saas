"""webhook routes and the user's pending market choice

webhook_routes maps an unguessable URL token to a tenant. It is the one table
here WITHOUT a row policy, and deliberately: Telegram calls with no idea which
customer its bot belongs to, so the tenant must be resolved before any tenant
context exists. A policy keyed on the current tenant would make every webhook
404. The table holds nothing but a random token and a tenant id, so an unscoped
read of it discloses nothing.

telegram_users.pending_market remembers which market a user picked before being
asked for a UID. It lives in the database rather than in memory because a
redeploy between the button press and the UID must not lose the choice.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-12 11:47:11.050313

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('webhook_routes',
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('provider', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_webhook_routes_tenant_id'), 'webhook_routes', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_webhook_routes_token'), 'webhook_routes', ['token'], unique=True)
    op.add_column('telegram_users', sa.Column('pending_market', sa.Enum('CRYPTO', 'FOREX', name='market', native_enum=False, length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('telegram_users', 'pending_market')
    op.drop_index(op.f('ix_webhook_routes_token'), table_name='webhook_routes')
    op.drop_index(op.f('ix_webhook_routes_tenant_id'), table_name='webhook_routes')
    op.drop_table('webhook_routes')
