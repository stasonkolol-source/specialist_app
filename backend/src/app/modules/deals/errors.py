"""Ошибки модуля deals со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import ConflictError, DomainValidationError, NotFoundError


class DealNotFoundError(NotFoundError):
    """Сделки нет или человек в ней не участвует (чужая — тоже 404)."""

    code = "deal_not_found"


class DealNotActiveError(ConflictError):
    """Действие невозможно в текущем статусе сделки: уже завершена, отменена, под спором или ещё
    не подтверждена второй стороной."""

    code = "deal_not_active"
    public_params = ("deal_status",)


class InvalidDealError(DomainValidationError):
    """Поле сделки нарушает правило (`field`, `reason`): причина отмены, цена, название."""

    code = "invalid_deal"
    public_params = ("field", "reason")
