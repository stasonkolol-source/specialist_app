"""Ошибки модуля moderation со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import (
    ConcurrentModificationError,
    ConflictError,
    DomainValidationError,
    NotFoundError,
    RateLimitedError,
)


class CaseNotFoundError(NotFoundError):
    code = "case_not_found"


class CaseAlreadyOpenError(ConcurrentModificationError):
    """Параллельный запрос только что открыл кейс того же объекта: команда повторяется и
    дописывает повод в открытый кейс."""

    code = "case_already_open"


class CaseStateError(ConflictError):
    """Действие недоступно в текущем статусе кейса: решённый кейс не решают снова."""

    code = "case_state_conflict"


class CaseTakenError(ConflictError):
    """Кейс уже разбирает другой модератор."""

    code = "case_taken"


class CaseSupersededError(ConflictError):
    """Объект изменили после карточки: кейс закрыт как устаревший, решать — новый кейс с новой
    версией (ADV-11). Решение по устаревшему ничего не публикует и не скрывает."""

    code = "case_superseded"


class InvalidDecisionError(DomainValidationError):
    """Решение без машинного кода причины или с неверным кодом."""

    code = "invalid_decision"


class CaseKindError(ConflictError):
    """Кейс такого вида так не решить: спор по сделке (`dispute`) решается с исходом сделки —
    `cli dispute-resolve`, а не `moderation-decide`."""

    code = "case_kind_conflict"
    public_params = ("entity_type",)


class ReportTargetNotFoundError(NotFoundError):
    """Жаловаться не на что: объекта нет, он не виден жалующемуся (чужая переписка, снятый
    профиль) или аккаунт удалён."""

    code = "report_target_not_found"


class InvalidReportError(DomainValidationError):
    """Жалоба не подходит (`field`, `reason`): причина не для этого типа объекта, жалоба на
    себя или на свой объект, переписка не с этим человеком."""

    code = "invalid_report"
    public_params = ("field", "reason")


class ReportNotFoundError(NotFoundError):
    """Жалобы с таким id нет (Admin API)."""

    code = "report_not_found"


class ReportsLimitError(RateLimitedError):
    """За сутки отправлено максимум жалоб (§13.3: двадцать)."""

    code = "reports_limit"


class ReportAlreadyOpenError(ConcurrentModificationError):
    """Параллельный запрос только что записал ту же жалобу: команда повторяется и отдаёт её."""

    code = "report_already_open"


class AppealTargetNotFoundError(NotFoundError):
    """Обжаловать нечего: решения нет, оно не о вас, нарушения не нашли или это апелляция."""

    code = "appeal_target_not_found"


class AppealWindowClosedError(ConflictError):
    """Шесть месяцев с решения прошли: апелляцию уже не подать (§14.4)."""

    code = "appeal_window_closed"


class AppealAlreadyFiledError(ConcurrentModificationError):
    """Параллельный запрос только что подал апелляцию на то же решение: команда повторяется
    и отдаёт её."""

    code = "appeal_already_filed"
