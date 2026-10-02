"""События модуля messaging (ADR-0020 §2; ARCHITECTURE §11.5; DEVELOPMENT_PLAN 6.3a). Подписчики:
модерация (через ModerationRequested), уведомления о новом сообщении (6.3b), аналитика."""

from dataclasses import dataclass
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationStarted(DomainEvent):
    """Диалог начат: по отклику на заявку или прямым обращением к специалисту."""

    event_type = "messaging.ConversationStarted"
    conversation_id: UUID
    kind: str
    """ConversationKind: `job_response`, `direct`."""
    initiator_id: UserId
    client_id: UserId
    performer_id: UserId
    job_id: UUID | None
    response_id: UUID | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MessageSent(DomainEvent):
    """Участник написал в диалог: второй стороне — уведомление (6.3b), тексту — проверка."""

    event_type = "messaging.MessageSent"
    conversation_id: UUID
    message_id: UUID
    sender_id: UserId
    recipient_id: UserId
    sender_role: str
    """ParticipantRole отправителя: `client`, `performer`."""
    masked: bool
    """Контакты в тексте скрыты: договорённости ещё нет."""
