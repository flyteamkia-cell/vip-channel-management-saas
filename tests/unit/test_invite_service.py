"""InviteService — the centralised, idempotent invite path (PHASE0 §26 BUG-01)."""

from datetime import timedelta
from uuid import uuid4

import pytest

from app.adapters.persistence.models import TelegramChannel, VIPMembership, utcnow
from app.adapters.providers.telegram_mock import MockTelegramProvider
from app.application.exceptions import ProviderUnavailableError
from app.domain.enums import Market, MembershipStatus
from app.services.invite_service import DEFAULT_INVITE_TTL, InviteService

TENANT = uuid4()


def channel() -> TelegramChannel:
    return TelegramChannel(tenant_id=TENANT, market=Market.CRYPTO, chat_id=-1001234567890)


def membership() -> VIPMembership:
    return VIPMembership(
        tenant_id=TENANT,
        user_id=uuid4(),
        channel_id=uuid4(),
        status=MembershipStatus.PENDING,
    )


@pytest.mark.asyncio
async def test_a_first_call_mints_a_single_use_link() -> None:
    telegram = MockTelegramProvider()
    result = await InviteService(telegram).issue(TENANT, membership(), channel())

    assert result.reused is False
    assert result.link.startswith("https://t.me/+")
    # member_limit=1: an invite that can be forwarded is not access control.
    assert telegram.invites_created == [(-1001234567890, 1)]


@pytest.mark.asyncio
async def test_calling_twice_returns_the_same_link_and_mints_nothing_new() -> None:
    """A retried webhook or a double tap must not create a second entry."""
    telegram = MockTelegramProvider()
    service = InviteService(telegram)
    member = membership()

    first = await service.issue(TENANT, member, channel())
    second = await service.issue(TENANT, member, channel())

    assert second.reused is True
    assert second.link == first.link
    assert len(telegram.invites_created) == 1


@pytest.mark.asyncio
async def test_an_expired_link_is_replaced() -> None:
    telegram = MockTelegramProvider()
    service = InviteService(telegram)
    member = membership()

    first = await service.issue(TENANT, member, channel())
    later = utcnow() + DEFAULT_INVITE_TTL + timedelta(minutes=1)
    second = await service.issue(TENANT, member, channel(), now=later)

    assert second.reused is False
    assert second.link != first.link
    assert len(telegram.invites_created) == 2


@pytest.mark.asyncio
async def test_the_membership_records_the_link_and_advances_to_invited() -> None:
    member = membership()
    await InviteService(MockTelegramProvider()).issue(TENANT, member, channel())

    assert member.status is MembershipStatus.INVITED
    assert member.invite_link is not None
    assert member.invite_issued_at is not None


@pytest.mark.asyncio
async def test_an_active_member_keeps_that_status() -> None:
    """Re-issuing to someone already in the channel must not demote them."""
    member = membership()
    member.status = MembershipStatus.ACTIVE
    await InviteService(MockTelegramProvider()).issue(TENANT, member, channel())
    assert member.status is MembershipStatus.ACTIVE


@pytest.mark.asyncio
async def test_a_telegram_failure_leaves_no_half_written_membership() -> None:
    """The prototype's failure mode exactly: `invited` in the database, no link.

    Raising rather than swallowing is what lets the caller's transaction roll
    back, so the record and the channel cannot disagree.
    """
    member = membership()
    telegram = MockTelegramProvider(unavailable=True)

    with pytest.raises(ProviderUnavailableError):
        await InviteService(telegram).issue(TENANT, member, channel())

    assert member.invite_link is None
    assert member.status is MembershipStatus.PENDING


@pytest.mark.asyncio
async def test_a_revoked_membership_gets_a_fresh_link_not_the_stale_one() -> None:
    """A returning member must not be handed the invite that was revoked."""
    telegram = MockTelegramProvider()
    service = InviteService(telegram)
    member = membership()

    first = await service.issue(TENANT, member, channel())
    member.status = MembershipStatus.REVOKED

    second = await service.issue(TENANT, member, channel())
    assert second.reused is False
    assert second.link != first.link
