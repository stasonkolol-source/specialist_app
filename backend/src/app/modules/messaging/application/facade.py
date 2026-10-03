"""Фасад messaging (ADR-0020 §6): модерация читает и скрывает сообщения в своей транзакции,
уведомления спрашивают, что сказать о новых сообщениях (6.3b)."""

import math
from datetime import datetime
from typing import Final
from uuid import UUID

from app.modules.messaging.api import MessageForReview, MessageNotice, ResponseTime
from app.modules.messaging.application.ports import ConversationQueries, MessageStore, Presence
from app.modules.messaging.domain.message import MessageKind, MessageModeration
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId
from app.platform.text.contact_masking import mask_contacts

PREVIEW_CHARS: Final = 100
"""Начало сообщения в уведомлении: дальше «…»."""


class MessagingFacade:
    def __init__(
        self,
        uow: UnitOfWork,
        messages: MessageStore,
        queries: ConversationQueries,
        presence: Presence,
    ) -> None:
        self._uow, self._messages = uow, messages
        self._queries, self._presence = queries, presence

    async def message_for_review(self, message_id: UUID) -> MessageForReview | None:
        message = await self._messages.get(message_id)
        if (
            message is None
            or message.sender_id is None
            or not message.body
            or message.moderation is MessageModeration.HIDDEN
        ):
            return None
        # контакты — правило переписки, не модерации: до договорённости они уже скрыты, после —
        # разрешены (ADR-0010); проверяется остальной текст
        return MessageForReview(sender_id=message.sender_id, text=mask_contacts(message.body))

    async def approve_message(self, message_id: UUID) -> None:
        self._uow.require_active()
        await self._messages.moderate(message_id, hidden=False)

    async def hide_message(self, message_id: UUID) -> None:
        self._uow.require_active()
        await self._messages.moderate(message_id, hidden=True)

    async def message_notice(
        self, conversation_id: UUID, recipient_id: UserId
    ) -> MessageNotice | None:
        if await self._presence.is_viewing(conversation_id, recipient_id):
            return None  # смотрит диалог прямо сейчас
        view = await self._queries.view(conversation_id, recipient_id)
        if view is None or view.unread == 0:
            return None
        last, preview = view.last_message, None
        if (
            last is not None
            and last.sender_id == view.counterpart_id
            and last.kind is MessageKind.TEXT
            and last.body
            and last.moderation is not MessageModeration.HIDDEN
        ):
            preview = _preview(last.body)
        return MessageNotice(sender_id=view.counterpart_id, unread=view.unread, preview=preview)

    async def response_times(
        self, *, since: datetime, min_conversations: int
    ) -> list[ResponseTime]:
        stats = await self._queries.response_stats(since=since, min_conversations=min_conversations)
        return [
            ResponseTime(
                performer_id=stat.performer_id,
                minutes=max(1, math.ceil(stat.median_seconds / 60)),
                conversations=stat.conversations,
            )
            for stat in stats
        ]

    async def unread_total(self, user_id: UserId) -> int:
        return await self._queries.unread_total(user_id)

    async def message_sender(self, message_id: UUID, viewer_id: UserId) -> UserId | None:
        message = await self._messages.get(message_id)
        if message is None or message.sender_id is None:
            return None
        if await self._queries.view(message.conversation_id, viewer_id) is None:
            return None  # чужая переписка — как несуществующая
        return message.sender_id

    async def counterpart(self, conversation_id: UUID, user_id: UserId) -> UserId | None:
        view = await self._queries.view(conversation_id, user_id)
        return view.counterpart_id if view is not None else None


def _preview(body: str) -> str:
    text = " ".join(body.split())
    return text if len(text) <= PREVIEW_CHARS else text[: PREVIEW_CHARS - 1].rstrip() + "…"
