"""Ошибки модуля notifications со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import ConflictError, DomainValidationError, NotFoundError


class TelegramNotLinkedError(ConflictError):
    """У пользователя нет Telegram-аккаунта (вошёл иначе или удалён): писать в бот некуда."""

    code = "telegram_not_linked"


class MandatoryGroupError(DomainValidationError):
    """Служебные уведомления (решения модерации, санкции) не выключаются: без них человек
    не узнает, почему контент не виден или действие запрещено."""

    code = "notification_group_mandatory"
    public_params = ("group",)


class BroadcastStateError(ConflictError):
    """Действие не подходит рассылке в этом статусе: начать можно только черновик, отменить —
    до завершения."""

    code = "broadcast_state"
    public_params = ("broadcast_status", "action")


class BroadcastNotFoundError(NotFoundError):
    code = "broadcast_not_found"
