"""Telegram's entry point into the application.

Thin by design (§33): parse the update, run the flow, send the replies. Nothing
is decided here.

The route is public to the tenant middleware because Telegram cannot send an
X-Tenant-ID header — it has no idea which of our customers its bot belongs to.
The tenant is resolved from an unguessable path token instead, which is why
`webhook_routes` is the one table that is not row-scoped: the lookup must
happen before a tenant context can exist.

Telegram retries an update until it gets 200, so every path returns 200 even
when the work fails. Returning 500 would make Telegram redeliver the same
message, and a flow that is not idempotent for every branch would then act
twice. The failure is logged and the user is answered, not replayed.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.adapters.persistence.models import WebhookRoute
from app.application.exceptions import ProviderUnavailableError
from app.core import database
from app.core.tenant_scope import bind_tenant
from app.domain import messages
from app.domain.enums import ProviderType
from app.services.bot_conversation import BotConversation, IncomingUpdate
from app.services.invite_service import InviteService
from app.services.provider_factory import MissingCredentialError, ProviderFactory
from app.services.referral_onboarding import ReferralOnboardingService

logger = logging.getLogger("vip_saas.telegram")

router = APIRouter(prefix="/telegram", tags=["telegram"])

#: Prefix the tenant middleware treats as public. Registered in main.py.
WEBHOOK_PATH_PREFIX = "/api/v1/telegram/"


def parse_update(payload: dict[str, Any]) -> IncomingUpdate | None:
    """Pull out the few fields the flow uses, or None for updates we ignore.

    Telegram sends many kinds of update; anything that is not a private message
    or a button press is not part of this flow and must be acknowledged, not
    processed.
    """
    if (callback := payload.get("callback_query")) is not None:
        sender = callback.get("from") or {}
        chat = (callback.get("message") or {}).get("chat") or {}
        return IncomingUpdate(
            chat_id=int(chat.get("id") or sender.get("id") or 0),
            user_id=int(sender.get("id") or 0),
            callback_data=callback.get("data"),
            username=sender.get("username"),
            first_name=sender.get("first_name"),
        )

    message = payload.get("message") or payload.get("edited_message")
    if not message:
        return None
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    if chat.get("type") not in (None, "private"):
        return None
    return IncomingUpdate(
        chat_id=int(chat.get("id") or 0),
        user_id=int(sender.get("id") or 0),
        text=message.get("text"),
        username=sender.get("username"),
        first_name=sender.get("first_name"),
    )


@router.post("/{token}")
async def receive_update(token: str, request: Request) -> Response:
    payload = await request.json()

    # The routing lookup runs on an unscoped session on purpose: there is no
    # tenant yet, and this table holds nothing but a token and a tenant id.
    async with database.AsyncSessionFactory() as routing_session:
        route = (
            await routing_session.execute(
                select(WebhookRoute).where(WebhookRoute.token == token)
            )
        ).scalar_one_or_none()
        tenant_id = route.tenant_id if route else None

    if tenant_id is None:
        # A wrong token is not told it is wrong. 200 keeps Telegram from
        # retrying and the body says nothing a prober can use.
        logger.warning("webhook called with an unknown token")
        return Response(status_code=200)

    update = parse_update(payload)
    if update is None or not update.user_id:
        return Response(status_code=200)

    async with database.AsyncSessionFactory() as session:
        bind_tenant(session, tenant_id)
        factory = ProviderFactory(session)
        try:
            referral = await factory.referral_provider(tenant_id, ProviderType.BITUNIX)
            telegram = await factory.telegram(tenant_id)
        except MissingCredentialError as exc:
            logger.info("tenant %s is not fully configured: %s", tenant_id, exc)
            return Response(status_code=200)

        conversation = BotConversation(
            session,
            ReferralOnboardingService(session, referral, InviteService(telegram)),
        )
        try:
            result = await conversation.handle(tenant_id, update)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("tenant %s: failed to handle update", tenant_id)
            result = None

        if result is None:
            # Answer rather than go silent, and do not let Telegram redeliver.
            try:
                await telegram.send_message(update.chat_id, messages.PROVIDER_UNAVAILABLE)
            except ProviderUnavailableError:
                pass
            return Response(status_code=200)

        for reply in result.replies:
            try:
                await telegram.send_message(
                    update.chat_id, reply.text, reply_markup=reply.reply_markup
                )
            except ProviderUnavailableError:
                logger.warning("tenant %s: could not deliver a reply", tenant_id)

    return Response(status_code=200)
