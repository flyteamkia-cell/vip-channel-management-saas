"""Domain vocabulary.

Every state name here comes from PHASE0_SPECIFICATION.md. They are stored as
VARCHAR with a CHECK constraint rather than a native PostgreSQL ENUM: adding a
value to a native enum is a migration that cannot run inside a transaction on
older servers, and the type is invisible to SQLite, which the unit layer uses.
A checked VARCHAR gives the same protection on both.
"""

from enum import StrEnum


class Market(StrEnum):
    """PHASE0 §27 — a tenant may run several markets side by side."""

    CRYPTO = "CRYPTO"
    FOREX = "FOREX"


class AccessType(StrEnum):
    """PHASE0 §10 — how the entitlement was earned, not how it is enforced."""

    REFERRAL = "REFERRAL"
    PAID = "PAID"
    TRIAL = "TRIAL"


class SubscriptionStatus(StrEnum):
    """PHASE0 §11 — the user's right to access."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class MembershipStatus(StrEnum):
    """PHASE0 §11 — the actual Telegram access state.

    Kept separate from SubscriptionStatus on purpose: an entitlement can be
    ACTIVE while the Telegram side is still PENDING because the invite has not
    been delivered, and an EXPIRED entitlement leaves a REVOKED membership plus
    an intact history. Collapsing them loses that.
    """

    PENDING = "PENDING"
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ReferralAccountStatus(StrEnum):
    """PHASE0 §21 — lifecycle of the link between a user and an exchange UID."""

    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ComplianceState(StrEnum):
    """PHASE0 §22.

    PROVIDER_UNAVAILABLE and VERIFICATION_PENDING are deliberately in the same
    enum as the user-fault states. The whole point of §22 is that an exchange
    outage must never be recorded as user inactivity, and the cheapest way to
    guarantee that is to make "we could not tell" a state the code must handle
    explicitly rather than an exception that defaults to NON_COMPLIANT.
    """

    COMPLIANT = "COMPLIANT"
    WARNING = "WARNING"
    NON_COMPLIANT = "NON_COMPLIANT"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"


class ProviderType(StrEnum):
    """PHASE0 §2 — which external system a stored credential belongs to."""

    BITUNIX = "BITUNIX"
    EPLANET = "EPLANET"
    TELEGRAM = "TELEGRAM"


class JobRunState(StrEnum):
    """PHASE0 §32 — the lifecycle of one claimed scheduled run."""

    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
