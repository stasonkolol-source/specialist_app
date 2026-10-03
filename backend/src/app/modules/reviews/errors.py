"""Ошибки модуля reviews со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import (
    ConflictError,
    DomainValidationError,
    ForbiddenError,
    NotFoundError,
)


class ReviewNotFoundError(NotFoundError):
    """Отзыва нет, он удалён или ещё не опубликован (ответить на него нельзя)."""

    code = "review_not_found"


class ReviewNotAllowedError(ConflictError):
    """Отзыв по этой сделке оставить нельзя (`reason`): `not_completed` — сделка не завершена,
    `window_closed` — прошло 14 дней после завершения, `not_client` — в MVP отзыв пишет только
    клиент."""

    code = "review_not_allowed"
    public_params = ("reason",)


class ReviewExistsError(ConflictError):
    """По сделке уже есть отзыв этого автора (`review_id`): отзыв не редактируется."""

    code = "review_exists"
    public_params = ("review_id",)


class InvalidReviewError(DomainValidationError):
    """Отзыв или ответ нарушает правило (`field`, `reason`): оценка вне 1–5, неизвестный
    критерий, текст длиннее 2000 символов, пустой ответ."""

    code = "invalid_review"
    public_params = ("field", "reason")


class NotReviewSubjectError(ForbiddenError):
    """Отвечает на отзыв только тот, о ком он написан."""

    code = "not_review_subject"


class ReplyExistsError(ConflictError):
    """На отзыв уже ответили: ответ один и не редактируется."""

    code = "reply_exists"
