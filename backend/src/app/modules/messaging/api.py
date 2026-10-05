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

    async def message_for_card(self, message_id: UUID) -> MessageForReview | None:
        """Текст сообщения для карточки кейса в чате модераторов (2.5b) — и скрытого флагом или
        модератором: контакты замаскированы, как для проверки. Системное или стёртое — None."""
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

    async def unread_total(self, user_id: UserId) -> int:
        """Непрочитанные сообщения во всех диалогах — бейдж «Сообщения N» таббара (6.4)."""
        ...

    async def message_sender(self, message_id: UUID, viewer_id: UserId) -> UserId | None:
        """Автор сообщения, которое видит `viewer_id` — участник его диалога (жалоба, 4.7);
        системное, чужой диалог или нет такого — None."""
        ...

    async def counterpart(self, conversation_id: UUID, user_id: UserId) -> UserId | None:
        """Вторая сторона диалога для участника (жалоба из меню чата S30, 4.7); не участник или
        нет диалога — None."""
        ...

    async def deal_conversation(self, deal_id: UUID, response_id: UUID | None) -> UUID | None:
        """Чат сделки — «Написать» на S26 (UX_GUIDANCE №2): диалог, где договорились, или диалог
        выбранного отклика; нет такого — None. Стороны сделки проверяет вызывающий."""
        ...
