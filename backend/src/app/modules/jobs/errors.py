"""Ошибки модуля jobs со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    RateLimitedError,
)


class JobNotFoundError(NotFoundError):
    """Заявки нет, она удалена или не видна этому пользователю (чужая — тоже 404)."""

    code = "job_not_found"


class InvalidJobError(DomainValidationError):
    """Поле заявки нарушает правило (`field`, `reason`): длина, бюджет, даты, фото."""

    code = "invalid_job"
    public_params = ("field", "reason")


class JobNotOpenError(ConflictError):
    """Действие невозможно в текущем статусе заявки (§8.3: `job_not_open`)."""

    code = "job_not_open"
    public_params = ("job_status",)


class JobExtendLimitError(ConflictError):
    """Заявку уже продлевали максимальное число раз (§7.9: три)."""

    code = "job_extend_limit"
    public_params = ("limit",)


class JobCategoryError(DomainValidationError):
    """Категория не принимает заявки: неактивна, запрещена или заявки в ней выключены."""

    code = "job_category_unavailable"


class ActiveJobsLimitError(RateLimitedError):
    """У новичка уже максимум активных заявок (§13.3: три) — закройте одну."""

    code = "active_jobs_limit"


class DailyJobsLimitError(RateLimitedError):
    """За сутки уже создано максимум заявок для этого уровня доверия (§13.3)."""

    code = "daily_jobs_limit"
