"""Ошибки модуля specialists со стабильными code (ADR-0020 §9)."""

from collections.abc import Sequence

from app.platform.kernel.errors import ConflictError, DomainValidationError, NotFoundError


class ProfileNotFoundError(NotFoundError):
    code = "profile_not_found"


class ProfileExistsError(ConflictError):
    """У пользователя уже есть профиль: в MVP — один на человека."""

    code = "profile_exists"


class ProfileStateError(ConflictError):
    """Действие недоступно в текущем статусе профиля (например, скрыть черновик)."""

    code = "profile_state_conflict"
    public_params = ("profile_status",)


class ProfileIncompleteError(ConflictError):
    """Профиль нельзя отправить на проверку: не заполнено обязательное (`missing`)."""

    code = "profile_incomplete"
    public_params = ("missing",)

    def __init__(self, *, missing: Sequence[str]) -> None:
        super().__init__(missing=list(missing))


class InvalidProfileError(DomainValidationError):
    """Поле профиля нарушает правило (`field`): длина, список, значение."""

    code = "invalid_profile"
    public_params = ("field",)


class CategoryNotAllowedError(DomainValidationError):
    """Категории нет, она выключена или запрещена для профилей."""

    code = "category_not_allowed"
    public_params = ("category_id",)


class DistrictNotAllowedError(DomainValidationError):
    """Района нет или он не в городе профиля."""

    code = "district_not_allowed"
    public_params = ("district_id",)
