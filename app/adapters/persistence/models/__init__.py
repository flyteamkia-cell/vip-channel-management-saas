"""SQLAlchemy models.

Importing this package registers every table on ``Base.metadata``. Alembic's
env.py and the test fixtures import ``Base`` from here, so a model that is not
re-exported below is invisible to autogenerate and to schema creation — which
is the classic "no such table" failure. Add new models to BOTH the import list
and ``__all__``.
"""

from app.adapters.persistence.models.base import (
    Base,
    TenantScoped,
    TimestampedEntity,
    utcnow,
)
from app.adapters.persistence.models.membership import (
    ReferralAccount,
    Subscription,
    TelegramUser,
    TradingActivitySnapshot,
    VIPMembership,
)
from app.adapters.persistence.models.payment import PaymentRecordTable
from app.adapters.persistence.models.tenant import (
    ProviderCredential,
    ReferralProgramConfig,
    TelegramBotConfig,
    TelegramChannel,
    Tenant,
)

__all__ = [
    "Base",
    "PaymentRecordTable",
    "ProviderCredential",
    "ReferralAccount",
    "ReferralProgramConfig",
    "Subscription",
    "TelegramBotConfig",
    "TelegramChannel",
    "TelegramUser",
    "Tenant",
    "TenantScoped",
    "TimestampedEntity",
    "TradingActivitySnapshot",
    "VIPMembership",
    "utcnow",
]
