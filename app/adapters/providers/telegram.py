"""Telegram Bot API adapter.

Endpoints and parameters are those the n8n prototype already used in
production — createChatInviteLink, getChatMember, banChatMember,
unbanChatMember, sendMessage — so nothing here is invented (§38).

The bot token is passed in, never read from a module constant or the
environment: each tenant runs its own bot (§1), and the token arrives decrypted
from that tenant's ProviderCredential for the duration of one call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.application.exceptions import ProviderUnavailableError
from app.application.ports.telegram_provider import (
    BotIdentity,
    ChatMemberStatus,
    TelegramProvider,
)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramBotProvider(TelegramProvider):
    def __init__(
        self,
        bot_token: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = TELEGRAM_API_BASE,
        timeout: float = 15.0,
    ) -> None:
        self._token = bot_token
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        url = f"{self._base_url}/bot{self._token}/{method}"
        body = {k: v for k, v in payload.items() if v is not None}
        try:
            if self._client is not None:
                response = await self._client.post(url, json=body, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(url, json=body)
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # The token is in the URL, so the exception text is never included
            # verbatim -- §2 forbids a credential reaching the logs, and an
            # httpx error message carries the request URL.
            raise ProviderUnavailableError(
                f"Telegram {method} failed: {type(exc).__name__}"
            ) from None

        if not data.get("ok"):
            raise ProviderUnavailableError(
                f"Telegram {method} returned "
                f"{data.get('error_code')}: {data.get('description')}"
            )
        return data.get("result")

    async def get_me(self) -> BotIdentity:
        result = await self._call("getMe", {})
        return BotIdentity(id=int(result["id"]), username=result.get("username"))

    async def create_invite_link(
        self,
        chat_id: int,
        *,
        member_limit: int = 1,
        expire_date: datetime | None = None,
        name: str | None = None,
    ) -> str:
        result = await self._call(
            "createChatInviteLink",
            {
                "chat_id": chat_id,
                "member_limit": member_limit,
                "expire_date": int(expire_date.timestamp()) if expire_date else None,
                "name": name,
            },
        )
        return str(result["invite_link"])

    async def get_chat_member(self, chat_id: int, user_id: int) -> ChatMemberStatus:
        result = await self._call(
            "getChatMember", {"chat_id": chat_id, "user_id": user_id}
        )
        try:
            return ChatMemberStatus(result["status"])
        except ValueError:
            # An unfamiliar status means Telegram added one. Treating it as
            # "absent" would quietly remove real members, so it is an outage.
            raise ProviderUnavailableError(
                f"Telegram returned an unknown chat member status: {result.get('status')!r}"
            ) from None

    async def ban_chat_member(self, chat_id: int, user_id: int) -> None:
        await self._call("banChatMember", {"chat_id": chat_id, "user_id": user_id})

    async def unban_chat_member(self, chat_id: int, user_id: int) -> None:
        await self._call(
            "unbanChatMember",
            {"chat_id": chat_id, "user_id": user_id, "only_if_banned": True},
        )

    async def send_message(
        self, chat_id: int, text: str, *, reply_markup: dict | None = None
    ) -> None:
        await self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            },
        )
