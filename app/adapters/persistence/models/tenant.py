from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.persistence.models.base import Base, TenantScoped, TimestampedEntity
from app.domain.enums import Market, ProviderType


class Tenant(TimestampedEntity, Base):
    """A customer of the platform.

    Deliberately NOT TenantScoped. This is the registry that defines tenants;
    a row has to be created before any tenant context exists, so a row policy
    keyed on the current tenant would make the first insert impossible. Access
    to it belongs to an admin surface with its own authorisation, never to the
    tenant-facing API.
    """

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ProviderCredential(TenantScoped, TimestampedEntity, Base):
    """PHASE0 §2 — an external secret, encrypted at rest.

    The plaintext never touches this table: `encrypted_secret` holds Fernet
    ciphertext and the key lives in the environment (see app.core.crypto), so a
    database dump on its own discloses nothing. `last_four` exists so an admin
    screen can show which credential is stored without the service ever being
    able to display the secret back.
    """

    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider_type",
            "credential_name",
            name="uq_provider_credentials_tenant_provider_name",
        ),
    )

    provider_type: Mapped[ProviderType] = mapped_column(
        Enum(ProviderType, native_enum=False, length=32), nullable=False
    )
    credential_name: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_secret: Mapped[str] = mapped_column(String(4096), nullable=False)
    last_four: Mapped[str | None] = mapped_column(String(4), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ReferralProgramConfig(TenantScoped, TimestampedEntity, Base):
    """PHASE0 §5, §7, §18, §19 — the tenant's referral programme, as data.

    Every business number the spec calls configurable lives here rather than in
    code: the minimum balance (§5 — 300 USD today, an admin's edit tomorrow),
    the qualifying-trade rule (§7), the IB id (§19). BUG-03 in §26 happened
    because a threshold was a literal someone could mistype; a column cannot be
    mistyped in a deploy.

    `referral_link` is what the bot hands the user at sign-up: the tenant
    supplies their own, so each customer recruits under their own affiliate
    code.
    """

    __tablename__ = "referral_program_configs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider_type", "market", name="uq_referral_config_tenant_provider_market"
        ),
    )

    provider_type: Mapped[ProviderType] = mapped_column(
        Enum(ProviderType, native_enum=False, length=32), nullable=False
    )
    market: Mapped[Market] = mapped_column(
        Enum(Market, native_enum=False, length=16), nullable=False
    )
    referral_link: Mapped[str] = mapped_column(String(500), nullable=False)
    ib_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Numeric(30, 8): balances are quoted in USD today but read from exchanges
    # that report crypto precision. Two decimal places would round a real
    # balance away, which is the failure §16 exists to prevent.
    minimum_balance: Mapped[Decimal] = mapped_column(
        Numeric(30, 8), nullable=False, default=Decimal(300)
    )
    minimum_trades_per_period: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    trade_period_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    compliance_grace_period_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TelegramChannel(TenantScoped, TimestampedEntity, Base):
    """PHASE0 §27 — a VIP destination, resolved from configuration.

    BUG-04 was a hard-coded channel id that removed forex members from the
    crypto channel. Nothing in the codebase may name a chat id; every
    membership operation resolves it from this table by (tenant, market).
    """

    __tablename__ = "telegram_channels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "market", name="uq_telegram_channels_tenant_market"),
        UniqueConstraint("tenant_id", "chat_id", name="uq_telegram_channels_tenant_chat"),
    )

    market: Mapped[Market] = mapped_column(
        Enum(Market, native_enum=False, length=16), nullable=False
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TelegramBotConfig(TenantScoped, TimestampedEntity, Base):
    """PHASE0 §1, §29 — the tenant's own bot.

    The token is not here. It is a ProviderCredential, referenced by id, so the
    rule in §2 ("never in source, never in logs, never in API responses") holds
    by construction rather than by discipline.

    `verified_at` is only set once §29's checks have actually passed — token
    valid, channel present, permissions sufficient. Until then the integration
    is configured but not trusted.
    """

    __tablename__ = "telegram_bot_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_telegram_bot_configs_tenant"),
    )

    credential_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    bot_username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
