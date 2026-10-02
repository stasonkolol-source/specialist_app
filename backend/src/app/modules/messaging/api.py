"""Контракт модуля messaging для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из messaging только этот файл.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.messaging.errors import ConversationNotFoundError as ConversationNotFoundError
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageForReview:
    """Сообщение для конвейера модерации (адаптер цели `message`, §14.1)."""

    sender_id: UserId
    text: str


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
