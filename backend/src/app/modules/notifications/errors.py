"""Ошибки модуля notifications со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import ConflictError, DomainValidationError


class TelegramNotLinkedError(ConflictError):
    """У пользователя нет Telegram-аккаунта (вошёл иначе или удалён): писать в бот некуда."""

    code = "telegram_not_linked"


class MandatoryGroupError(DomainValidationError):
    """Служебные уведомления (решения модерации, санкции) не выключаются: без них человек
    не узнает, почему контент не виден или действие запрещено."""

    code = "notification_group_mandatory"
    public_params = ("group",)
