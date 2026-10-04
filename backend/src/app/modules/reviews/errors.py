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


class ReviewInviteNotFoundError(NotFoundError):
    """Ссылки-приглашения нет, её отозвали, она истекла или по ней уже оставили отзыв —
    одинаково, чтобы по ответу не угадать, что со ссылкой (7.6а)."""

    code = "review_invite_not_found"


class ReviewInvitesFullError(ConflictError):
    """Приглашений на «отзыв до платформы» уже `limit` (5): освобождает место отозванная или
    истёкшая ссылка."""

    code = "review_invites_full"
    public_params = ("limit",)


class ReviewInviteUsedError(ConflictError):
    """По ссылке уже оставили отзыв: отозвать её нельзя."""

    code = "review_invite_used"


class ReviewInvitesUnavailableError(ConflictError):
    """Приглашать прошлых клиентов можно, когда профиль специалиста опубликован: иначе ссылку
    некому открыть."""

    code = "review_invites_unavailable"


class OwnProfileReviewError(ConflictError):
    """Отзыв о себе по своей же ссылке не оставить."""

    code = "own_profile_review"


class PrePlatformReviewExistsError(ConflictError):
    """Этот человек уже оставил «отзыв до платформы» об этом специалисте: один на профиль."""

    code = "pre_platform_review_exists"
