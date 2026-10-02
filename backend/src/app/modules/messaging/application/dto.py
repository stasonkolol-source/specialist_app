"""Чтение переписки (S29, S30; DEVELOPMENT_PLAN 6.3a): диалоги участника и сообщения диалога."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.messaging.domain.conversation import (
    ConversationKind,
    ConversationStatus,
    ParticipantRole,
)
from app.modules.messaging.domain.message import Message
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationView:
    """Диалог глазами участника: вторая сторона, последнее сообщение и непрочитанные."""

    id: UUID
    kind: ConversationKind
    status: ConversationStatus
    my_role: ParticipantRole
    counterpart_id: UserId
    job_id: UUID | None
    response_id: UUID | None
    deal_id: UUID | None
    last_message: Message | None
    unread: int
    created_at: datetime
    last_message_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MessagesPage:
    """Страница сообщений по порядку (старые → новые) и курсоры в обе стороны."""

    items: tuple[Message, ...]
    older: str | None
    """Курсор более ранних; None — это начало диалога."""
    newer: str | None
    """Курсор, с которого спрашивать новые (поллинг S30)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseStat:
    """Как быстро исполнитель отвечает (6.3b): медиана от первого сообщения клиента в диалоге до
    первого ответа исполнителя."""

    performer_id: UserId
    median_seconds: float
    conversations: int
    """Диалогов с ответом в окне — по ним медиана."""
