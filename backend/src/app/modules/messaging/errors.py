"""Ошибки модуля messaging со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    RateLimitedError,
)


class ConversationNotFoundError(NotFoundError):
    """Диалога нет или человек в нём не участвует (чужой — тоже 404)."""

    code = "conversation_not_found"


class ConversationClosedError(ConflictError):
    """Диалог закрыт или заблокирован: писать в него нельзя."""

    code = "conversation_closed"
    public_params = ("conversation_status",)


class CannotStartConversationError(ConflictError):
    """Начать диалог нельзя: отклик не виден клиенту, его отозвали, писать самому себе."""

    code = "cannot_start_conversation"
    public_params = ("reason",)


class InvalidMessageError(DomainValidationError):
    """Сообщение нарушает правило (`field`, `reason`): пустое или длиннее 4000 символов."""

    code = "invalid_message"
    public_params = ("field", "reason")


class MessagesLimitError(RateLimitedError):
    """За час отправлено максимум сообщений для этого уровня доверия (§13.3: 20 или 100)."""

    code = "messages_limit"


class ConversationsLimitError(RateLimitedError):
    """За час начато максимум новых диалогов (§13.3: пять)."""

    code = "conversations_limit"
