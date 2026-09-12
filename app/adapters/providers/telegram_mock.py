"""In-memory Telegram, for tests and local runs without a bot token.

Records what was asked of it so tests can assert on effects that are otherwise
invisible: that an invite was minted exactly once, that a removal was followed
by an unban, that nothing was sent to a user whose provider check failed.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime

from app.application.exceptions import ProviderUnavailableError
from app.application.ports.telegram_provider import (
    BotIdentity,
    ChatMemberStatus,
    TelegramProvider,
)


@dataclass
class SentMessage:
    chat_id: int
    text: str
    reply_markup: dict | None = None


@dataclass
class MockTelegramProvider(TelegramProvider):
    identity: BotIdentity = field(default_factory=lambda: BotIdentity(id=1, username="test_bot"))
    unavailable: bool = False
    member_status: dict[tuple[int, int], ChatMemberStatus] = field(default_factory=dict)

    invites_created: list[tuple[int, int]] = field(default_factory=list)
    banned: list[tuple[int, int]] = field(default_factory=list)
    unbanned: list[tuple[int, int]] = field(default_factory=list)
    messages: list[SentMessage] = field(default_factory=list)
    _counter: itertools.count = field(default_factory=lambda: itertools.count(1))

    def _guard(self) -> None:
        if self.unavailable:
            raise ProviderUnavailableError("mock telegram is configured as unavailable")

    async def get_me(self) -> BotIdentity:
        self._guard()
        return self.identity

    async def create_invite_link(
        self,
        chat_id: int,
        *,
        member_limit: int = 1,
        expire_date: datetime | None = None,
        name: str | None = None,
    ) -> str:
        self._guard()
        self.invites_created.append((chat_id, member_limit))
        return f"https://t.me/+mock{next(self._counter)}"

    async def get_chat_member(self, chat_id: int, user_id: int) -> ChatMemberStatus:
        self._guard()
        return self.member_status.get((chat_id, user_id), ChatMemberStatus.LEFT)

    async def ban_chat_member(self, chat_id: int, user_id: int) -> None:
        self._guard()
        self.banned.append((chat_id, user_id))
        self.member_status[(chat_id, user_id)] = ChatMemberStatus.KICKED

    async def unban_chat_member(self, chat_id: int, user_id: int) -> None:
        self._guard()
        self.unbanned.append((chat_id, user_id))
        self.member_status[(chat_id, user_id)] = ChatMemberStatus.LEFT

    async def send_message(
        self, chat_id: int, text: str, *, reply_markup: dict | None = None
    ) -> None:
        self._guard()
        self.messages.append(SentMessage(chat_id=chat_id, text=text, reply_markup=reply_markup))
