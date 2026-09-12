from uuid import UUID

from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.adapters.persistence.models.base import Base, TimestampedEntity


class WebhookRoute(TimestampedEntity, Base):
    """Maps an unguessable URL token to the tenant it belongs to.

    Deliberately NOT TenantScoped, and that is the whole reason it exists as a
    separate table: Telegram calls us with no idea which customer it is calling
    about, so the tenant must be resolved *before* any tenant context exists. A
    row policy keyed on the current tenant would make the lookup return nothing
    and every webhook would 404.

    Keeping it apart from telegram_bot_configs means the unscoped read touches
    a table holding nothing but a random token and a tenant id — no secrets, no
    configuration, nothing worth reading if the token is ever guessed.

    The token is the authentication. Telegram's own secret_token header is
    checked too where configured, but the path must already be unguessable
    because a leaked URL is the whole attack.
    """

    __tablename__ = "webhook_routes"

    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="TELEGRAM")
