"""Контракт модуля messaging для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из messaging только этот файл.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.messaging.errors import ConversationNotFoundError as ConversationNotFoundError
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageForReview:
    """Сообщение для конвейера модерации (адаптер цели `message`, §14.1)."""

    sender_id: UserId
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageNotice:
    """Что сказать получателю о новых сообщениях (`message.received`, 6.3b)."""

    sender_id: UserId
    """Вторая сторона диалога: её имя — в заголовке."""
    unread: int
    preview: str | None
    """Начало последнего сообщения второй стороны, если это видимый текст; иначе None."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseTime:
    """«Обычно отвечает за …» (S08, 6.3b): медиана первого ответа исполнителя в диалогах."""

    performer_id: UserId
    minutes: int
    """Медиана, округлённая вверх до минуты (не меньше одной)."""
    conversations: int


class MessagingApi(Protocol):
    async def message_for_review(self, message_id: UUID) -> MessageForReview | None:
        """Текст сообщения участника; системное, стёртое или скрытое — None."""
        ...

    async def approve_message(self, message_id: UUID) -> None:
        """Проверка пройдена — в транзакции вызывающего: сообщение снова видно (после флага)."""
        ...

    async def hide_message(self, message_id: UUID) -> None:
        """Нарушение — в транзакции вызывающего: текст скрыт от второй стороны."""
        ...

    async def message_notice(
        self, conversation_id: UUID, recipient_id: UserId
    ) -> MessageNotice | None:
        """Новые сообщения для получателя; None — всё прочитано, диалог сейчас открыт или
        получатель в нём не участвует."""
        ...

    async def response_times(
        self, *, since: datetime, min_conversations: int
    ) -> list[ResponseTime]:
        """Медиана первого ответа исполнителей по диалогам, где клиент впервые написал после
        `since`; у кого диалогов с ответом меньше `min_conversations` — их нет в списке."""
        ...
