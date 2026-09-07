from abc import ABC, abstractmethod
from uuid import UUID


class TenantContextExtractorPort(ABC):
    @abstractmethod
    async def extract_tenant_id(self, headers: dict[str, str]) -> UUID | None:
        """Extract and validate tenant_id from HTTP request headers."""


class WebhookSignatureVerifierPort(ABC):
    @abstractmethod
    async def verify_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        """Verify HMAC/Ed25519 signature of incoming provider webhooks."""
