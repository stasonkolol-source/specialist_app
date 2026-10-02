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


class SavedJobsFullError(ConflictError):
    """В сохранённых у исполнителя уже максимум заявок (S12: сто)."""

    code = "saved_jobs_full"
    public_params = ("limit",)


class InvalidResponseError(DomainValidationError):
    """Поле отклика нарушает правило (`field`, `reason`): длина сообщения, цена, «когда смогу»."""

    code = "invalid_response"
    public_params = ("field", "reason")


class ResponseNotFoundError(NotFoundError):
    """Отклика нет, он удалён или не принадлежит этому исполнителю (чужой — тоже 404)."""

    code = "response_not_found"


class ResponseNotActiveError(ConflictError):
    """Клиент уже решил по отклику (выбран, отклонён, не выбран) или его отозвали."""

    code = "response_not_active"
    public_params = ("response_status",)


class AlreadyRespondedError(ConflictError):
    """Исполнитель уже откликался на эту заявку: отклик один, отозванный не повторяется."""

    code = "already_responded"


class OwnJobResponseError(ConflictError):
    """На свою заявку откликнуться нельзя."""

    code = "own_job"


class JobFullError(ConflictError):
    """Все места на заявке заняты (§7.9: пять активных откликов) — приём откликов закрыт."""

    code = "job_full"
    public_params = ("limit",)


class DailyResponsesLimitError(RateLimitedError):
    """За сутки уже отправлено максимум откликов для этого уровня доверия (§13.3)."""

    code = "daily_responses_limit"


class ActiveResponsesLimitError(ConflictError):
    """Откликов, ждущих решения клиента, уже столько, сколько позволяет тариф (v1, §15.2)."""

    code = "active_responses_limit"
    public_params = ("limit",)


class InvalidTemplateError(DomainValidationError):
    """Поле шаблона отклика нарушает правило (`field`, `reason`): название, сообщение, цена."""

    code = "invalid_response_template"
    public_params = ("field", "reason")


class TemplateNotFoundError(NotFoundError):
    """Шаблона нет, он удалён или чужой."""

    code = "response_template_not_found"


class TemplatesFullError(ConflictError):
    """У исполнителя уже максимум шаблонов (два) — удалите один, чтобы добавить новый."""

    code = "response_templates_full"
    public_params = ("limit",)


class JobInvitesFullError(ConflictError):
    """В заявку уже приглашено максимум специалистов (десять)."""

    code = "job_invites_full"
    public_params = ("limit",)


class InviteeNotFoundError(NotFoundError):
    """Пригласить или запросить некого: профиль не опубликован, скрыт, удалён или его автор под
    санкцией («заблокированного пригласить нельзя»)."""

    code = "invitee_not_found"


class OwnProfileInviteError(ConflictError):
    """Свой профиль в свою заявку не приглашают."""

    code = "own_profile_invite"
