"""The single place an invite link is created (PHASE0 §26, BUG-01).

The prototype generated invites on three separate branches — payment, referral
and trial — and one of them carried a malformed expression, so those users were
marked `invited` in the database while receiving no link at all. The database
said yes and the channel said no, and nothing noticed.

Two properties follow from having one implementation:

* **Idempotent.** Calling twice for a member who already holds a live link
  returns the same link. A retried webhook, a double tap on a button, or a
  replayed job cannot mint a second invite — which matters because each mint is
  an independent single-use entry to a paid channel.
* **Atomic in the way that counts.** The link is written to the membership row
  and the status advanced in the same transaction as the Telegram call's
  result. If Telegram fails we raise, the transaction rolls back, and the
  member is not left recorded as invited without a link.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.adapters.persistence.models import TelegramChannel, VIPMembership, utcnow
from app.application.ports.telegram_provider import TelegramProvider
from app.domain.enums import MembershipStatus

#: How long a freshly minted invite stays usable. Long enough that a user who
#: steps away comes back to a working link, short enough that a leaked one goes
#: stale. Configurable per tenant later; a constant is honest for now.
DEFAULT_INVITE_TTL = timedelta(days=1)

#: Statuses in which an existing link is still the right answer.
_LINK_IS_LIVE = (MembershipStatus.INVITED, MembershipStatus.ACTIVE)


@dataclass(frozen=True)
class IssuedInvite:
    link: str
    reused: bool


class InviteService:
    def __init__(self, telegram: TelegramProvider, ttl: timedelta = DEFAULT_INVITE_TTL) -> None:
        self._telegram = telegram
        self._ttl = ttl

    async def issue(
        self,
        tenant_id: UUID,
        membership: VIPMembership,
        channel: TelegramChannel,
        *,
        now: datetime | None = None,
    ) -> IssuedInvite:
        """Return a usable single-use invite for this membership.

        `channel` is passed in rather than looked up here so that the caller
        has already resolved it from (tenant, market) — no chat id is ever
        named in code (§26 BUG-04).
        """
        moment = now or utcnow()

        existing = self._live_link(membership, moment)
        if existing is not None:
            return IssuedInvite(link=existing, reused=True)

        link = await self._telegram.create_invite_link(
            channel.chat_id,
            member_limit=1,
            expire_date=moment + self._ttl,
            name=f"vip-{membership.user_id}",
        )

        membership.invite_link = link
        membership.invite_issued_at = moment
        if membership.status is not MembershipStatus.ACTIVE:
            membership.status = MembershipStatus.INVITED
        membership.tenant_id = tenant_id
        return IssuedInvite(link=link, reused=False)

    def _live_link(self, membership: VIPMembership, moment: datetime) -> str | None:
        if not membership.invite_link or membership.status not in _LINK_IS_LIVE:
            return None
        issued = membership.invite_issued_at
        if issued is None:
            return None
        if issued.tzinfo is None:
            # SQLite hands back naive datetimes; treat them as UTC rather than
            # letting the comparison below raise.
            issued = issued.replace(tzinfo=UTC)
        if issued + self._ttl <= moment:
            return None
        return membership.invite_link
