"""Ошибки модуля identity со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import (
    ConcurrentModificationError,
    ConflictError,
    DomainValidationError,
    ForbiddenError,
    NotFoundError,
)


class UserNotFoundError(NotFoundError):
    code = "user_not_found"


class SessionNotFoundError(NotFoundError):
    code = "session_not_found"


class AccountDeletedError(ForbiddenError):
    """Аккаунт удалён: войти в него нельзя (ZZPL — удаление по запросу, шаг 6.x)."""

    code = "account_deleted"


class UserAlreadyDeletedError(ConflictError):
    code = "user_already_deleted"


class ConcurrentLoginError(ConcurrentModificationError):
    """Два первых входа одного Telegram-аккаунта одновременно: второй повторяет запрос."""

    code = "concurrent_login"


class InvalidDisplayNameError(DomainValidationError):
    """Имя пустое после очистки от пробелов и невидимых символов."""

    code = "invalid_display_name"
