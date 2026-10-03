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


class CannotProposeError(ConflictError):
    """«Договорились» здесь нельзя (`reason`): в диалоге по отклику договорённость — выбор
    отклика клиентом (S24)."""

    code = "cannot_propose"
    public_params = ("reason",)


class DealInProgressError(ConflictError):
    """В диалоге уже идёт договорённость (`deal_id`): предложение ждёт ответа или сделка идёт."""

    code = "deal_in_progress"
    public_params = ("deal_id",)


class ContactsLockedError(ConflictError):
    """Контактом делятся только после договорённости: сделки `agreed` в диалоге нет."""

    code = "contacts_locked"


class InvalidContactError(DomainValidationError):
    """Контакт не принят (`reason`): нет username в Telegram, контакт чужой, подпись Telegram не
    сошлась или устарела."""

    code = "invalid_contact"
    public_params = ("reason",)
