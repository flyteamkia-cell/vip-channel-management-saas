"""stage 1: referral membership model

Adds the tables stage 1 needs: tenants and their Telegram/referral
configuration, encrypted provider credentials, users, referral accounts,
subscriptions, VIP memberships and trading-activity snapshots.

Also widens payment_records.amount from NUMERIC(12, 2) to NUMERIC(30, 8).
PHASE0 §11 lists Network and Asset alongside Amount, so the values are crypto:
USDT has 6 decimal places and BTC 8, and two would round a real transfer away
without raising anything. Done now, while the table is empty.

Every new tenant-scoped table gets the same forced row policy as 0002. The
predicate is repeated here rather than imported from application code on
purpose: a migration must keep meaning what it meant the day it ran, and a
shared helper would let a later edit silently rewrite history.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-12 11:00:48.293681

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Tables added by this revision that carry a tenant_id.
NEW_TENANT_SCOPED_TABLES = (
    "provider_credentials",
    "referral_accounts",
    "referral_program_configs",
    "subscriptions",
    "telegram_bot_configs",
    "telegram_channels",
    "telegram_users",
    "trading_activity_snapshots",
    "vip_memberships",
)

PREDICATE = "tenant_id = NULLIF(current_setting(\'app.tenant_id\', true), \'\')::uuid"


def _enable_row_policies() -> None:
    for table in NEW_TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({PREDICATE}) WITH CHECK ({PREDICATE})"
        )


def _disable_row_policies() -> None:
    for table in NEW_TENANT_SCOPED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.create_table('provider_credentials',
    sa.Column('provider_type', sa.Enum('BITUNIX', 'EPLANET', 'TELEGRAM', name='providertype', native_enum=False, length=32), nullable=False),
    sa.Column('credential_name', sa.String(length=100), nullable=False),
    sa.Column('encrypted_secret', sa.String(length=4096), nullable=False),
    sa.Column('last_four', sa.String(length=4), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'provider_type', 'credential_name', name='uq_provider_credentials_tenant_provider_name')
    )
    op.create_index(op.f('ix_provider_credentials_tenant_id'), 'provider_credentials', ['tenant_id'], unique=False)
    op.create_table('referral_accounts',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('provider_type', sa.Enum('BITUNIX', 'EPLANET', 'TELEGRAM', name='providertype', native_enum=False, length=32), nullable=False),
    sa.Column('market', sa.Enum('CRYPTO', 'FOREX', name='market', native_enum=False, length=16), nullable=False),
    sa.Column('uid', sa.String(length=128), nullable=False),
    sa.Column('status', sa.Enum('UNVERIFIED', 'VERIFIED', 'REJECTED', name='referralaccountstatus', native_enum=False, length=32), nullable=False),
    sa.Column('compliance_state', sa.Enum('COMPLIANT', 'WARNING', 'NON_COMPLIANT', 'SUSPENDED', 'REVOKED', 'PROVIDER_UNAVAILABLE', 'VERIFICATION_PENDING', name='compliancestate', native_enum=False, length=32), nullable=False),
    sa.Column('last_known_balance', sa.Numeric(precision=30, scale=8), nullable=True),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rejection_reason', sa.String(length=500), nullable=True),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'provider_type', 'uid', name='uq_referral_accounts_tenant_provider_uid')
    )
    op.create_index(op.f('ix_referral_accounts_tenant_id'), 'referral_accounts', ['tenant_id'], unique=False)
    op.create_index('ix_referral_accounts_tenant_user', 'referral_accounts', ['tenant_id', 'user_id'], unique=False)
    op.create_table('referral_program_configs',
    sa.Column('provider_type', sa.Enum('BITUNIX', 'EPLANET', 'TELEGRAM', name='providertype', native_enum=False, length=32), nullable=False),
    sa.Column('market', sa.Enum('CRYPTO', 'FOREX', name='market', native_enum=False, length=16), nullable=False),
    sa.Column('referral_link', sa.String(length=500), nullable=False),
    sa.Column('ib_id', sa.String(length=100), nullable=True),
    sa.Column('minimum_balance', sa.Numeric(precision=30, scale=8), nullable=False),
    sa.Column('minimum_trades_per_period', sa.Integer(), nullable=False),
    sa.Column('trade_period_days', sa.Integer(), nullable=False),
    sa.Column('compliance_grace_period_days', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'provider_type', 'market', name='uq_referral_config_tenant_provider_market')
    )
    op.create_index(op.f('ix_referral_program_configs_tenant_id'), 'referral_program_configs', ['tenant_id'], unique=False)
    op.create_table('subscriptions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('market', sa.Enum('CRYPTO', 'FOREX', name='market', native_enum=False, length=16), nullable=False),
    sa.Column('access_type', sa.Enum('REFERRAL', 'PAID', 'TRIAL', name='accesstype', native_enum=False, length=32), nullable=False),
    sa.Column('plan_code', sa.String(length=50), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'ACTIVE', 'EXPIRED', 'CANCELLED', name='subscriptionstatus', native_enum=False, length=32), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_reference', sa.String(length=200), nullable=True),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_subscriptions_tenant_id'), 'subscriptions', ['tenant_id'], unique=False)
    op.create_index('ix_subscriptions_tenant_status', 'subscriptions', ['tenant_id', 'status'], unique=False)
    op.create_index('ix_subscriptions_tenant_user', 'subscriptions', ['tenant_id', 'user_id'], unique=False)
    op.create_table('telegram_bot_configs',
    sa.Column('credential_id', sa.Uuid(), nullable=False),
    sa.Column('bot_username', sa.String(length=100), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', name='uq_telegram_bot_configs_tenant')
    )
    op.create_index(op.f('ix_telegram_bot_configs_tenant_id'), 'telegram_bot_configs', ['tenant_id'], unique=False)
    op.create_table('telegram_channels',
    sa.Column('market', sa.Enum('CRYPTO', 'FOREX', name='market', native_enum=False, length=16), nullable=False),
    sa.Column('chat_id', sa.BigInteger(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'chat_id', name='uq_telegram_channels_tenant_chat'),
    sa.UniqueConstraint('tenant_id', 'market', name='uq_telegram_channels_tenant_market')
    )
    op.create_index(op.f('ix_telegram_channels_tenant_id'), 'telegram_channels', ['tenant_id'], unique=False)
    op.create_table('telegram_users',
    sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=True),
    sa.Column('first_name', sa.String(length=200), nullable=True),
    sa.Column('language_code', sa.String(length=16), nullable=True),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'telegram_user_id', name='uq_telegram_users_tenant_tg_id')
    )
    op.create_index(op.f('ix_telegram_users_tenant_id'), 'telegram_users', ['tenant_id'], unique=False)
    op.create_table('tenants',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('trading_activity_snapshots',
    sa.Column('referral_account_id', sa.Uuid(), nullable=False),
    sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('qualifying_trades', sa.Integer(), nullable=False),
    sa.Column('balance', sa.Numeric(precision=30, scale=8), nullable=True),
    sa.Column('still_under_referral', sa.Boolean(), nullable=True),
    sa.Column('provider_state', sa.Enum('COMPLIANT', 'WARNING', 'NON_COMPLIANT', 'SUSPENDED', 'REVOKED', 'PROVIDER_UNAVAILABLE', 'VERIFICATION_PENDING', name='compliancestate', native_enum=False, length=32), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'referral_account_id', 'period_start', name='uq_trading_snapshots_account_period')
    )
    op.create_index(op.f('ix_trading_activity_snapshots_tenant_id'), 'trading_activity_snapshots', ['tenant_id'], unique=False)
    op.create_table('vip_memberships',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('channel_id', sa.Uuid(), nullable=False),
    sa.Column('subscription_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.Enum('PENDING', 'INVITED', 'ACTIVE', 'SUSPENDED', 'EXPIRED', 'REVOKED', name='membershipstatus', native_enum=False, length=32), nullable=False),
    sa.Column('invite_link', sa.String(length=500), nullable=True),
    sa.Column('invite_issued_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revocation_reason', sa.String(length=500), nullable=True),
    sa.Column('warnings_sent', sa.Integer(), nullable=False),
    sa.Column('last_warning_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'user_id', 'channel_id', name='uq_vip_memberships_tenant_user_channel')
    )
    op.create_index(op.f('ix_vip_memberships_tenant_id'), 'vip_memberships', ['tenant_id'], unique=False)
    op.create_index('ix_vip_memberships_tenant_status', 'vip_memberships', ['tenant_id', 'status'], unique=False)
    # batch_alter_table, not a bare alter_column: SQLite cannot change a column
    # type in place, so batch mode rebuilds the table there. On PostgreSQL it
    # emits the plain ALTER. The unit layer runs these same migrations, so a
    # PostgreSQL-only statement would break it.
    with op.batch_alter_table("payment_records") as batch_op:
        batch_op.alter_column(
            "amount",
            existing_type=sa.NUMERIC(precision=12, scale=2),
            type_=sa.Numeric(precision=30, scale=8),
            existing_nullable=False,
        )


    if op.get_context().dialect.name == "postgresql":
        _enable_row_policies()


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        _disable_row_policies()

    with op.batch_alter_table("payment_records") as batch_op:
        batch_op.alter_column(
            "amount",
            existing_type=sa.Numeric(precision=30, scale=8),
            type_=sa.NUMERIC(precision=12, scale=2),
            existing_nullable=False,
        )
    op.drop_index('ix_vip_memberships_tenant_status', table_name='vip_memberships')
    op.drop_index(op.f('ix_vip_memberships_tenant_id'), table_name='vip_memberships')
    op.drop_table('vip_memberships')
    op.drop_index(op.f('ix_trading_activity_snapshots_tenant_id'), table_name='trading_activity_snapshots')
    op.drop_table('trading_activity_snapshots')
    op.drop_table('tenants')
    op.drop_index(op.f('ix_telegram_users_tenant_id'), table_name='telegram_users')
    op.drop_table('telegram_users')
    op.drop_index(op.f('ix_telegram_channels_tenant_id'), table_name='telegram_channels')
    op.drop_table('telegram_channels')
    op.drop_index(op.f('ix_telegram_bot_configs_tenant_id'), table_name='telegram_bot_configs')
    op.drop_table('telegram_bot_configs')
    op.drop_index('ix_subscriptions_tenant_user', table_name='subscriptions')
    op.drop_index('ix_subscriptions_tenant_status', table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_tenant_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index(op.f('ix_referral_program_configs_tenant_id'), table_name='referral_program_configs')
    op.drop_table('referral_program_configs')
    op.drop_index('ix_referral_accounts_tenant_user', table_name='referral_accounts')
    op.drop_index(op.f('ix_referral_accounts_tenant_id'), table_name='referral_accounts')
    op.drop_table('referral_accounts')
    op.drop_index(op.f('ix_provider_credentials_tenant_id'), table_name='provider_credentials')
    op.drop_table('provider_credentials')
