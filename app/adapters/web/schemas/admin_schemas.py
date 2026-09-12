"""Admin panel payloads (PHASE0 §2, §3, §27).

A secret goes IN through these schemas and never comes back out. Every response
model here carries `last_four` and never `encrypted_secret` or a plaintext
value: §2 forbids a credential appearing in an API response, and the way to
guarantee it is to have no field capable of carrying one.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import Market, ProviderType


class CredentialUpsertRequest(BaseModel):
    provider_type: ProviderType
    credential_name: str = Field(min_length=1, max_length=100)
    secret: str = Field(min_length=1, max_length=2048, repr=False)

    # repr=False on `secret` keeps it out of the string form of this model,
    # which is what ends up in tracebacks and error logs.
    model_config = ConfigDict(extra="forbid")


class CredentialResponse(BaseModel):
    id: UUID
    provider_type: ProviderType
    credential_name: str
    last_four: str | None
    verified_at: datetime | None
    updated_at: datetime


class ReferralConfigRequest(BaseModel):
    provider_type: ProviderType = ProviderType.BITUNIX
    market: Market = Market.CRYPTO
    referral_link: str = Field(min_length=1, max_length=500)
    ib_id: str | None = Field(default=None, max_length=100)
    minimum_balance: Decimal = Field(default=Decimal(300), ge=0)
    minimum_trades_per_period: int = Field(default=1, ge=0)
    trade_period_days: int = Field(default=7, ge=1)
    compliance_grace_period_days: int = Field(default=30, ge=0)
    is_active: bool = True

    model_config = ConfigDict(extra="forbid")


class ReferralConfigResponse(BaseModel):
    id: UUID
    provider_type: ProviderType
    market: Market
    referral_link: str
    ib_id: str | None
    minimum_balance: Decimal
    minimum_trades_per_period: int
    trade_period_days: int
    compliance_grace_period_days: int
    is_active: bool


class ChannelRequest(BaseModel):
    market: Market
    chat_id: int
    title: str | None = Field(default=None, max_length=255)
    is_active: bool = True

    model_config = ConfigDict(extra="forbid")


class ChannelResponse(BaseModel):
    id: UUID
    market: Market
    chat_id: int
    title: str | None
    is_active: bool


class BotConfigRequest(BaseModel):
    bot_token: str = Field(min_length=1, max_length=512, repr=False)

    model_config = ConfigDict(extra="forbid")


class BotConfigResponse(BaseModel):
    id: UUID
    bot_username: str | None
    token_last_four: str | None
    verified_at: datetime | None


class IntegrationCheckResponse(BaseModel):
    """The outcome of §29's pre-flight checks."""

    bot_ok: bool
    bot_username: str | None = None
    referral_ok: bool = False
    channels_checked: list[Market] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.bot_ok and self.referral_ok and not self.problems
