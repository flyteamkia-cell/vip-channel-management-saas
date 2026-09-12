"""Tenant-scoped data access.

Every method still takes `tenant_id` explicitly even though the session is
already bound to a tenant and PostgreSQL enforces it (see
app.core.tenant_scope). The automatic layers are a floor, not a replacement: a
signature that cannot be called without naming a tenant keeps the intent
visible at the call site, and the two mechanisms catching the same mistake is
the point of defence in depth.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import (
    Base,
    PaymentRecordTable,
    ProviderCredential,
    ReferralAccount,
    ReferralProgramConfig,
    Subscription,
    TelegramBotConfig,
    TelegramChannel,
    TelegramUser,
    Tenant,
    TradingActivitySnapshot,
    VIPMembership,
)
from app.domain.enums import Market, MembershipStatus, ProviderType


class TenantScopedRepository[ModelT: Base]:
    """Shared CRUD for anything carrying a tenant_id."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, tenant_id: UUID, entity_id: UUID) -> ModelT | None:
        stmt = select(self.model).where(
            self.model.tenant_id == tenant_id,  # type: ignore[attr-defined]
            self.model.id == entity_id,  # type: ignore[attr-defined]
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_all(
        self, tenant_id: UUID, limit: int = 100, offset: int = 0
    ) -> Sequence[ModelT]:
        stmt = (
            select(self.model)
            .where(self.model.tenant_id == tenant_id)  # type: ignore[attr-defined]
            .limit(limit)
            .offset(offset)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def save(self, tenant_id: UUID, entity: ModelT) -> ModelT:
        entity.tenant_id = tenant_id  # type: ignore[attr-defined]
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, tenant_id: UUID, entity_id: UUID) -> bool:
        stmt = delete(self.model).where(
            self.model.tenant_id == tenant_id,  # type: ignore[attr-defined]
            self.model.id == entity_id,  # type: ignore[attr-defined]
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0 if isinstance(result, CursorResult) else False


class SQLAlchemyPaymentRepository(TenantScopedRepository[PaymentRecordTable]):
    model = PaymentRecordTable


class TelegramUserRepository(TenantScopedRepository[TelegramUser]):
    model = TelegramUser

    async def get_by_telegram_id(
        self, tenant_id: UUID, telegram_user_id: int
    ) -> TelegramUser | None:
        stmt = select(TelegramUser).where(
            TelegramUser.tenant_id == tenant_id,
            TelegramUser.telegram_user_id == telegram_user_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class ReferralAccountRepository(TenantScopedRepository[ReferralAccount]):
    model = ReferralAccount

    async def get_by_uid(
        self, tenant_id: UUID, provider_type: ProviderType, uid: str
    ) -> ReferralAccount | None:
        """Used before enrolling a UID, so one exchange account backs one member."""
        stmt = select(ReferralAccount).where(
            ReferralAccount.tenant_id == tenant_id,
            ReferralAccount.provider_type == provider_type,
            ReferralAccount.uid == uid,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, tenant_id: UUID, user_id: UUID) -> Sequence[ReferralAccount]:
        stmt = select(ReferralAccount).where(
            ReferralAccount.tenant_id == tenant_id, ReferralAccount.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalars().all()


class SubscriptionRepository(TenantScopedRepository[Subscription]):
    model = Subscription

    async def get_active_for_user(
        self, tenant_id: UUID, user_id: UUID, market: Market
    ) -> Subscription | None:
        stmt = select(Subscription).where(
            Subscription.tenant_id == tenant_id,
            Subscription.user_id == user_id,
            Subscription.market == market,
        )
        return (await self.session.execute(stmt)).scalars().first()


class MembershipRepository(TenantScopedRepository[VIPMembership]):
    model = VIPMembership

    async def get_for_user_and_channel(
        self, tenant_id: UUID, user_id: UUID, channel_id: UUID
    ) -> VIPMembership | None:
        stmt = select(VIPMembership).where(
            VIPMembership.tenant_id == tenant_id,
            VIPMembership.user_id == user_id,
            VIPMembership.channel_id == channel_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_by_status(
        self, tenant_id: UUID, *statuses: MembershipStatus
    ) -> Sequence[VIPMembership]:
        stmt = select(VIPMembership).where(
            VIPMembership.tenant_id == tenant_id, VIPMembership.status.in_(statuses)
        )
        return (await self.session.execute(stmt)).scalars().all()


class TelegramChannelRepository(TenantScopedRepository[TelegramChannel]):
    model = TelegramChannel

    async def get_for_market(self, tenant_id: UUID, market: Market) -> TelegramChannel | None:
        """The only sanctioned way to learn a chat id (§26 BUG-04)."""
        stmt = select(TelegramChannel).where(
            TelegramChannel.tenant_id == tenant_id,
            TelegramChannel.market == market,
            TelegramChannel.is_active.is_(True),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class ReferralProgramConfigRepository(TenantScopedRepository[ReferralProgramConfig]):
    model = ReferralProgramConfig

    async def get_for(
        self, tenant_id: UUID, provider_type: ProviderType, market: Market
    ) -> ReferralProgramConfig | None:
        stmt = select(ReferralProgramConfig).where(
            ReferralProgramConfig.tenant_id == tenant_id,
            ReferralProgramConfig.provider_type == provider_type,
            ReferralProgramConfig.market == market,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class ProviderCredentialRepository(TenantScopedRepository[ProviderCredential]):
    model = ProviderCredential

    async def get_named(
        self, tenant_id: UUID, provider_type: ProviderType, credential_name: str
    ) -> ProviderCredential | None:
        stmt = select(ProviderCredential).where(
            ProviderCredential.tenant_id == tenant_id,
            ProviderCredential.provider_type == provider_type,
            ProviderCredential.credential_name == credential_name,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class TelegramBotConfigRepository(TenantScopedRepository[TelegramBotConfig]):
    model = TelegramBotConfig

    async def get(self, tenant_id: UUID) -> TelegramBotConfig | None:
        stmt = select(TelegramBotConfig).where(TelegramBotConfig.tenant_id == tenant_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()


class TradingActivityRepository(TenantScopedRepository[TradingActivitySnapshot]):
    model = TradingActivitySnapshot


class TenantRepository:
    """The registry. Not tenant-scoped — see the Tenant model for why."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID) -> Tenant | None:
        return (
            await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Tenant | None:
        return (
            await self.session.execute(select(Tenant).where(Tenant.slug == slug))
        ).scalar_one_or_none()

    async def create(self, tenant: Tenant) -> Tenant:
        self.session.add(tenant)
        await self.session.flush()
        await self.session.refresh(tenant)
        return tenant
