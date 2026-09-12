"""Admin surface: where a customer configures their own integration.

This is what makes the product sellable rather than a single channel owner's
bot. Every tenant enters their own Bitunix key, their own bot token, their own
channel ids and their own thresholds, and nothing is ever read from a constant
in the source (§1, §2, §19, §27).

Two rules hold across every route here:

* a secret is write-only — it goes in and never comes back, not even to the
  admin who typed it (§2). Responses carry `last_four` so a screen can show
  *which* key is installed without the service being able to show what it is;
* the tenant comes from the middleware, never from the body. An admin cannot
  write another tenant's configuration by naming it in JSON (§28).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.models import (
    ProviderCredential,
    ReferralProgramConfig,
    TelegramBotConfig,
    TelegramChannel,
    utcnow,
)
from app.adapters.persistence.repositories import (
    ProviderCredentialRepository,
    ReferralProgramConfigRepository,
    TelegramBotConfigRepository,
    TelegramChannelRepository,
)
from app.adapters.web.dependencies import get_tenant_id, get_tenant_session
from app.adapters.web.schemas.admin_schemas import (
    BotConfigRequest,
    BotConfigResponse,
    ChannelRequest,
    ChannelResponse,
    CredentialResponse,
    CredentialUpsertRequest,
    IntegrationCheckResponse,
    ReferralConfigRequest,
    ReferralConfigResponse,
)
from app.application.exceptions import ProviderUnavailableError
from app.core.crypto import CredentialEncryptionError, encrypt_secret, last_four
from app.domain.enums import Market, ProviderType
from app.services.provider_factory import (
    TELEGRAM_BOT_TOKEN,
    MissingCredentialError,
    ProviderFactory,
)

router = APIRouter(prefix="/admin", tags=["admin"])


async def _store_secret(
    session: AsyncSession,
    tenant_id: UUID,
    provider_type: ProviderType,
    name: str,
    secret: str,
) -> ProviderCredential:
    repo = ProviderCredentialRepository(session)
    existing = await repo.get_named(tenant_id, provider_type, name)
    try:
        ciphertext = encrypt_secret(secret)
    except CredentialEncryptionError as exc:
        # A misconfigured server must not fall back to storing plaintext.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    if existing is not None:
        existing.encrypted_secret = ciphertext
        existing.last_four = last_four(secret)
        # Rotating a key invalidates whatever we previously verified with it.
        existing.verified_at = None
        return existing

    return await repo.save(
        tenant_id,
        ProviderCredential(
            tenant_id=tenant_id,
            provider_type=provider_type,
            credential_name=name,
            encrypted_secret=ciphertext,
            last_four=last_four(secret),
        ),
    )


@router.put("/credentials", response_model=CredentialResponse)
async def upsert_credential(
    payload: CredentialUpsertRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> CredentialResponse:
    """Store or rotate one secret. The value is never returned."""
    record = await _store_secret(
        session, tenant_id, payload.provider_type, payload.credential_name, payload.secret
    )
    await session.flush()
    return CredentialResponse(
        id=record.id,
        provider_type=record.provider_type,
        credential_name=record.credential_name,
        last_four=record.last_four,
        verified_at=record.verified_at,
        updated_at=record.updated_at or utcnow(),
    )


@router.get("/credentials", response_model=list[CredentialResponse])
async def list_credentials(
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[CredentialResponse]:
    records = await ProviderCredentialRepository(session).list_all(tenant_id)
    return [
        CredentialResponse(
            id=r.id,
            provider_type=r.provider_type,
            credential_name=r.credential_name,
            last_four=r.last_four,
            verified_at=r.verified_at,
            updated_at=r.updated_at or utcnow(),
        )
        for r in records
    ]


@router.put("/referral-config", response_model=ReferralConfigResponse)
async def upsert_referral_config(
    payload: ReferralConfigRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> ReferralConfigResponse:
    """The tenant's own referral link and thresholds (§5, §7, §18, §19)."""
    repo = ReferralProgramConfigRepository(session)
    config = await repo.get_for(tenant_id, payload.provider_type, payload.market)
    if config is None:
        config = ReferralProgramConfig(
            tenant_id=tenant_id,
            provider_type=payload.provider_type,
            market=payload.market,
            referral_link=payload.referral_link,
        )
        config = await repo.save(tenant_id, config)

    config.referral_link = payload.referral_link
    config.ib_id = payload.ib_id
    config.minimum_balance = payload.minimum_balance
    config.minimum_trades_per_period = payload.minimum_trades_per_period
    config.trade_period_days = payload.trade_period_days
    config.compliance_grace_period_days = payload.compliance_grace_period_days
    config.is_active = payload.is_active
    await session.flush()
    # Refresh so the response carries the database's canonical form. Without
    # it, a create and an update of the same value answer differently
    # ("300.00000000" vs "300"), and an admin screen that round-trips the
    # payload would keep showing a diff that is not there.
    await session.refresh(config)

    return ReferralConfigResponse.model_validate(config, from_attributes=True)


@router.put("/channels", response_model=ChannelResponse)
async def upsert_channel(
    payload: ChannelRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> ChannelResponse:
    """Register a VIP destination (§27).

    Chat ids live only here. BUG-04 was one hard-coded in a removal branch, so
    every membership operation resolves the channel from (tenant, market).
    """
    repo = TelegramChannelRepository(session)
    channel = await repo.get_for_market(tenant_id, payload.market)
    if channel is None:
        channel = await repo.save(
            tenant_id,
            TelegramChannel(
                tenant_id=tenant_id, market=payload.market, chat_id=payload.chat_id
            ),
        )
    channel.chat_id = payload.chat_id
    channel.title = payload.title
    channel.is_active = payload.is_active
    await session.flush()
    await session.refresh(channel)
    return ChannelResponse.model_validate(channel, from_attributes=True)


@router.get("/channels", response_model=list[ChannelResponse])
async def list_channels(
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[ChannelResponse]:
    channels = await TelegramChannelRepository(session).list_all(tenant_id)
    return [ChannelResponse.model_validate(c, from_attributes=True) for c in channels]


@router.put("/telegram-bot", response_model=BotConfigResponse)
async def upsert_bot(
    payload: BotConfigRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> BotConfigResponse:
    """Install the tenant's bot token, and confirm it works (§29).

    The token is stored as a credential and referenced by id; the config row
    never holds it. Verification is attempted immediately so a typo is caught
    here rather than by a user whose invite silently never arrives — but a
    Telegram outage does not block saving, since the key itself may be fine.
    """
    credential = await _store_secret(
        session, tenant_id, ProviderType.TELEGRAM, TELEGRAM_BOT_TOKEN, payload.bot_token
    )
    await session.flush()

    repo = TelegramBotConfigRepository(session)
    config = await repo.get(tenant_id)
    if config is None:
        config = await repo.save(
            tenant_id, TelegramBotConfig(tenant_id=tenant_id, credential_id=credential.id)
        )
    config.credential_id = credential.id

    try:
        identity = await (await ProviderFactory(session).telegram(tenant_id)).get_me()
        config.bot_username = identity.username
        config.verified_at = utcnow()
        credential.verified_at = config.verified_at
    except (ProviderUnavailableError, MissingCredentialError):
        config.bot_username = None
        config.verified_at = None

    await session.flush()
    return BotConfigResponse(
        id=config.id,
        bot_username=config.bot_username,
        token_last_four=credential.last_four,
        verified_at=config.verified_at,
    )


@router.post("/integration-check", response_model=IntegrationCheckResponse)
async def check_integration(
    tenant_id: UUID = Depends(get_tenant_id),
    session: AsyncSession = Depends(get_tenant_session),
) -> IntegrationCheckResponse:
    """§29 — say plainly what is missing instead of failing later, silently."""
    factory = ProviderFactory(session)
    result = IntegrationCheckResponse(bot_ok=False)

    try:
        identity = await (await factory.telegram(tenant_id)).get_me()
        result.bot_ok = True
        result.bot_username = identity.username
    except MissingCredentialError:
        result.problems.append("Telegram bot token is not configured")
    except ProviderUnavailableError as exc:
        result.problems.append(f"Telegram rejected the token: {exc}")

    try:
        await factory.referral_provider(tenant_id, ProviderType.BITUNIX)
        result.referral_ok = True
    except MissingCredentialError as exc:
        result.problems.append(str(exc))

    channels = await TelegramChannelRepository(session).list_all(tenant_id)
    result.channels_checked = [c.market for c in channels if c.is_active]
    if not result.channels_checked:
        result.problems.append("no active VIP channel is configured")

    configs = await ReferralProgramConfigRepository(session).list_all(tenant_id)
    for market in result.channels_checked:
        if not any(c.market == market and c.is_active for c in configs):
            result.problems.append(f"no referral programme configured for {Market(market).value}")

    return result
