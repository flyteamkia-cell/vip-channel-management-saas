"""Building a provider for one tenant, from that tenant's stored credentials.

This is the seam that makes the product a SaaS rather than one channel owner's
bot: nothing anywhere names an API key, and every outbound call is made with
the credentials of the tenant the request belongs to (§1, §28). A credential is
decrypted here, used, and never stored back in plaintext or logged.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.persistence.repositories import (
    ProviderCredentialRepository,
    TelegramBotConfigRepository,
)
from app.adapters.providers.bitunix import BitunixCredentials, BitunixReferralProvider
from app.adapters.providers.telegram import TelegramBotProvider
from app.application.exceptions import ApplicationError
from app.application.ports.referral_provider import ReferralProvider
from app.application.ports.telegram_provider import TelegramProvider
from app.core.crypto import decrypt_secret
from app.domain.enums import ProviderType

#: Credential names are part of the configuration contract, not free text: the
#: admin surface writes these exact names and the factory reads them.
BITUNIX_API_KEY = "api_key"
BITUNIX_API_SECRET = "api_secret"
TELEGRAM_BOT_TOKEN = "bot_token"


class MissingCredentialError(ApplicationError):
    """A tenant has not finished configuring an integration.

    Distinct from ProviderUnavailableError: nothing is broken, the customer
    simply has not entered their key yet, and the admin surface should say so
    rather than reporting an outage.
    """


@dataclass(frozen=True)
class ProviderFactory:
    session: AsyncSession

    async def _secret(
        self, tenant_id: UUID, provider_type: ProviderType, name: str
    ) -> str:
        record = await ProviderCredentialRepository(self.session).get_named(
            tenant_id, provider_type, name
        )
        if record is None:
            raise MissingCredentialError(
                f"tenant has no {provider_type.value} credential named {name!r}"
            )
        return decrypt_secret(record.encrypted_secret)

    async def referral_provider(
        self, tenant_id: UUID, provider_type: ProviderType
    ) -> ReferralProvider:
        if provider_type is ProviderType.BITUNIX:
            return BitunixReferralProvider(
                BitunixCredentials(
                    api_key=await self._secret(tenant_id, provider_type, BITUNIX_API_KEY),
                    api_secret=await self._secret(tenant_id, provider_type, BITUNIX_API_SECRET),
                )
            )
        raise MissingCredentialError(
            f"no referral adapter is implemented for {provider_type.value}"
        )

    async def telegram(self, tenant_id: UUID) -> TelegramProvider:
        config = await TelegramBotConfigRepository(self.session).get(tenant_id)
        if config is None:
            raise MissingCredentialError("tenant has not configured a Telegram bot")
        token = await self._secret(tenant_id, ProviderType.TELEGRAM, TELEGRAM_BOT_TOKEN)
        return TelegramBotProvider(bot_token=token)
