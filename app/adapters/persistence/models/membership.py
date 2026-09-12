from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.persistence.models.base import Base, TenantScoped, TimestampedEntity
from app.domain.enums import (
    AccessType,
    ComplianceState,
    Market,
    MembershipStatus,
    ProviderType,
    ReferralAccountStatus,
    SubscriptionStatus,
)


class TelegramUser(TenantScoped, TimestampedEntity, Base):
    """A person, as the bot knows them.

    Scoped per tenant even though one human may talk to several tenants' bots:
    from each tenant's side they are a separate member with separate
    entitlements, and joining them would be a cross-tenant leak (§28).
    """

    __tablename__ = "telegram_users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "telegram_user_id", name="uq_telegram_users_tenant_tg_id"),
    )

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)


class ReferralAccount(TenantScoped, TimestampedEntity, Base):
    """The claimed link between a user and an exchange account (§21).

    UNIQUE(tenant_id, provider_type, uid) is the anti-sharing rule: within a
    tenant a single exchange account backs at most one member, so two people
    cannot ride one qualifying balance. It stops at the tenant boundary on
    purpose — a global constraint would let one customer discover, through a
    duplicate error, that a UID is already enrolled with another customer,
    which is the §28 leak in miniature. The same open question applies to
    payment tx hashes (§15) and both should be settled together.

    `last_checked_at` and `compliance_state` are what make §22 possible: an
    exchange outage writes PROVIDER_UNAVAILABLE and leaves the previous
    verdict standing, instead of silently reading as "no trades".
    """

    __tablename__ = "referral_accounts"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider_type", "uid", name="uq_referral_accounts_tenant_provider_uid"
        ),
        Index("ix_referral_accounts_tenant_user", "tenant_id", "user_id"),
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    provider_type: Mapped[ProviderType] = mapped_column(
        Enum(ProviderType, native_enum=False, length=32), nullable=False
    )
    market: Mapped[Market] = mapped_column(
        Enum(Market, native_enum=False, length=16), nullable=False
    )
    uid: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[ReferralAccountStatus] = mapped_column(
        Enum(ReferralAccountStatus, native_enum=False, length=32),
        nullable=False,
        default=ReferralAccountStatus.UNVERIFIED,
    )
    compliance_state: Mapped[ComplianceState] = mapped_column(
        Enum(ComplianceState, native_enum=False, length=32),
        nullable=False,
        default=ComplianceState.VERIFICATION_PENDING,
    )
    last_known_balance: Mapped[Decimal | None] = mapped_column(Numeric(30, 8), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Subscription(TenantScoped, TimestampedEntity, Base):
    """PHASE0 §11 — the right to access, independent of how it was earned.

    A referral member and a paying member both land here, which is what lets
    stage 2 add payments without touching the membership machinery: payments
    will produce Subscriptions, and everything downstream already speaks
    Subscription.

    `ends_at` is nullable because a referral entitlement has no fixed term; it
    lasts while the user stays eligible, which the monitoring job decides.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_tenant_user", "tenant_id", "user_id"),
        Index("ix_subscriptions_tenant_status", "tenant_id", "status"),
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    market: Mapped[Market] = mapped_column(
        Enum(Market, native_enum=False, length=16), nullable=False
    )
    access_type: Mapped[AccessType] = mapped_column(
        Enum(AccessType, native_enum=False, length=32), nullable=False
    )
    plan_code: Mapped[str] = mapped_column(String(50), nullable=False, default="REFERRAL_FREE")
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, native_enum=False, length=32),
        nullable=False,
        default=SubscriptionStatus.PENDING,
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)


class VIPMembership(TenantScoped, TimestampedEntity, Base):
    """PHASE0 §11 — the actual Telegram access state, per channel.

    Per channel, not per user: §27 lets a tenant run a crypto and a forex
    channel, and BUG-04 was exactly the bug you get when one membership row
    stands for "in the channels, somehow". One row per (user, channel) means a
    removal names the channel it removes from.

    `invite_link` and `invite_issued_at` live here so InviteService can be
    idempotent (§26 BUG-01): a second call for a member who already holds an
    unused link returns that link instead of minting another.
    """

    __tablename__ = "vip_memberships"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "channel_id", name="uq_vip_memberships_tenant_user_channel"
        ),
        Index("ix_vip_memberships_tenant_status", "tenant_id", "status"),
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    channel_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    subscription_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, native_enum=False, length=32),
        nullable=False,
        default=MembershipStatus.PENDING,
    )
    invite_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    invite_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    warnings_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_warning_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TradingActivitySnapshot(TenantScoped, TimestampedEntity, Base):
    """PHASE0 §8 — what the exchange says the user did.

    Strictly separate from any user-submitted performance report. §8 is blunt
    about this: a screenshot is not evidence of a trade. Only rows here, sourced
    from a provider API, may satisfy the trading requirement.

    One row per (account, period) so the weekly job is replay-safe: re-running
    a period overwrites its own snapshot instead of appending a second verdict.
    """

    __tablename__ = "trading_activity_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "referral_account_id",
            "period_start",
            name="uq_trading_snapshots_account_period",
        ),
    )

    referral_account_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    qualifying_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    balance: Mapped[Decimal | None] = mapped_column(Numeric(30, 8), nullable=True)
    still_under_referral: Mapped[bool | None] = mapped_column(nullable=True)
    provider_state: Mapped[ComplianceState] = mapped_column(
        Enum(ComplianceState, native_enum=False, length=32),
        nullable=False,
        default=ComplianceState.VERIFICATION_PENDING,
    )
