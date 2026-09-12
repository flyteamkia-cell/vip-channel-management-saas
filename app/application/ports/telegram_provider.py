"""Contract for the Telegram side (PHASE0 §37 E).

Only I/O lives behind this. §33 is explicit that business logic must not sit
inside Telegram handlers, and the way to guarantee it is to give the rest of
the application an interface that can do nothing but talk to Telegram — then
the temptation to decide anything here has nowhere to live.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ChatMemberStatus(StrEnum):
    """Telegram's own vocabulary, not ours.

    Mapping it into our MembershipStatus is a decision the membership service
    makes; keeping the raw value here means a Telegram API change shows up in
    one adapter instead of rippling through the domain.
    """

    CREATOR = "creator"
    ADMINISTRATOR = "administrator"
    MEMBER = "member"
    RESTRICTED = "restricted"
    LEFT = "left"
    KICKED = "kicked"

    @property
    def is_present(self) -> bool:
        return self in {
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.RESTRICTED,
        }


@dataclass(frozen=True)
class BotIdentity:
    id: int
    username: str | None


class TelegramProvider(ABC):
    """Everything the product needs Telegram to do, and nothing else."""

    @abstractmethod
    async def get_me(self) -> BotIdentity:
        """Confirm the token works at all (§29, first check)."""

    @abstractmethod
    async def create_invite_link(
        self,
        chat_id: int,
        *,
        member_limit: int = 1,
        expire_date: datetime | None = None,
        name: str | None = None,
    ) -> str:
        """Mint a single-use invite.

        member_limit defaults to 1 because a VIP invite that can be forwarded
        is not access control. The caller decides expiry.
        """

    @abstractmethod
    async def get_chat_member(self, chat_id: int, user_id: int) -> ChatMemberStatus:
        """Whether the user is actually in the channel right now.

        The prototype marked members `invited` and never confirmed arrival, so
        its database and the channel drifted apart. Reconciliation needs this.
        """

    @abstractmethod
    async def ban_chat_member(self, chat_id: int, user_id: int) -> None:
        """Remove from the channel."""

    @abstractmethod
    async def unban_chat_member(self, chat_id: int, user_id: int) -> None:
        """Lift the ban so a later re-join is possible.

        Telegram's ban is sticky: removing a member without unbanning them
        makes a future renewal silently impossible.
        """

    @abstractmethod
    async def send_message(
        self, chat_id: int, text: str, *, reply_markup: dict | None = None
    ) -> None:
        """Send a message to a user or channel."""
