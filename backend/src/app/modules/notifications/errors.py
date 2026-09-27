"""Ошибки модуля notifications со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import ConflictError


class TelegramNotLinkedError(ConflictError):
    """У пользователя нет Telegram-аккаунта (вошёл иначе или удалён): писать в бот некуда."""

    code = "telegram_not_linked"
