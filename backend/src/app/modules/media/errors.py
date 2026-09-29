"""Ошибки модуля media со стабильными code (ADR-0020 §9)."""

from app.platform.kernel.errors import ConflictError, DomainValidationError, NotFoundError


class MediaNotFoundError(NotFoundError):
    """Файла нет или он чужой: владелец другого файла о нём не узнаёт."""

    code = "media_not_found"


class UnsupportedMediaTypeError(DomainValidationError):
    """Тип файла не из allow-list назначения (ARCHITECTURE §10.1); `allowed` — что можно."""

    code = "media_type_not_allowed"
    public_params = ("mime_type", "allowed")


class MediaTooLargeError(DomainValidationError):
    """Файл больше лимита назначения; `max_bytes` — лимит."""

    code = "media_too_large"
    public_params = ("max_bytes",)


class MediaPurposeNotAvailableError(DomainValidationError):
    """Назначение ещё закрыто: сообщения, отзывы и верификация — с v1."""

    code = "media_purpose_not_available"
    public_params = ("purpose",)


class MediaStateError(ConflictError):
    """Действие не подходит состоянию файла: например, ссылка на загрузку уже загруженного."""

    code = "media_state_conflict"
    public_params = ("media_status",)
    """Не `status`: это поле ответа RFC 9457 — HTTP-код."""


class UploadIncompleteError(ConflictError):
    """`complete` раньше, чем файл дошёл до хранилища: клиенту — догрузить и повторить.

    `missing_parts` — номера частей multipart, которых нет в запросе: их и догрузить.
    """

    code = "media_upload_incomplete"
    public_params = ("missing_parts",)


class UploadMismatchError(DomainValidationError):
    """В хранилище не тот файл: размер или тип отличаются от заявленных. Загрузка — `failed`."""

    code = "media_upload_mismatch"
