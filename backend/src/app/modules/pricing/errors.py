"""Ошибки модуля pricing со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import ConflictError, DomainValidationError, NotFoundError


class ServiceNotFoundError(NotFoundError):
    code = "service_not_found"


class InvalidServiceError(DomainValidationError):
    """Поле позиции прайса нарушает правило (`field`): название, цена, единица."""

    code = "invalid_service"
    public_params = ("field",)


class PriceListFullError(ConflictError):
    """В прайсе уже максимум позиций."""

    code = "price_list_full"
    public_params = ("limit",)


class NoProfileError(ConflictError):
    """Прайс ведут в профиле исполнителя: сначала профиль (S32a)."""

    code = "no_specialist_profile"
