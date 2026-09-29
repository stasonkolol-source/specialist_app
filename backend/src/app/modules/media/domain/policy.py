"""Что и сколько можно загружать (ARCHITECTURE §10.1, ADR-0007): назначение, тип, размер.

MVP принимает аватар, портфолио и фото к заявке; сообщения, отзывы и документы
верификации — v1 (их назначения уже в схеме, но загрузка закрыта). Тип — по MIME из
allow-list; заголовок клиента здесь только заявка: настоящий тип по magic bytes проверяет
обработка (2.2). Сколько файлов в портфолио или заявке — правило привязки (2.8a, 5.1),
а не загрузки.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.modules.media.errors import (
    MediaPurposeNotAvailableError,
    MediaTooLargeError,
    UnsupportedMediaTypeError,
)

MB: Final = 1024 * 1024


class MediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"


class MediaPurpose(StrEnum):
    AVATAR = "avatar"
    PORTFOLIO = "portfolio"
    JOB = "job"
    MESSAGE = "message"
    REVIEW = "review"
    VERIFICATION = "verification"


IMAGE_TYPES: Final = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)
VIDEO_TYPES: Final = frozenset({"video/mp4", "video/quicktime"})
DOCUMENT_TYPES: Final = frozenset({"application/pdf"})

FORMATS: Final = (
    ("image/jpeg", "JPEG"),
    ("image/png", "PNG"),
    ("image/webp", "WebP"),
    ("image/heic", "HEIC"),
    ("image/heif", "HEIC"),
    ("video/mp4", "MP4"),
    ("video/quicktime", "MOV"),
    ("application/pdf", "PDF"),
)
"""Имена форматов для текста ошибки, в порядке показа."""

MAX_BYTES: Final[dict[tuple[MediaPurpose, MediaKind], int]] = {
    (MediaPurpose.AVATAR, MediaKind.IMAGE): 10 * MB,
    (MediaPurpose.PORTFOLIO, MediaKind.IMAGE): 15 * MB,
    (MediaPurpose.PORTFOLIO, MediaKind.VIDEO): 200 * MB,
    (MediaPurpose.JOB, MediaKind.IMAGE): 15 * MB,
}
"""Лимит исходника по назначению и типу (§10.1). Пары нет — такой файл сюда не грузят."""

MVP_PURPOSES: Final = frozenset({MediaPurpose.AVATAR, MediaPurpose.PORTFOLIO, MediaPurpose.JOB})

MULTIPART_THRESHOLD: Final = 50 * MB
"""Видео больше 50 MB грузится частями (ADR-0007): обрыв сети не начинает загрузку заново."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UploadRule:
    kind: MediaKind
    max_bytes: int
    multipart: bool


def kind_of(mime_type: str) -> MediaKind | None:
    if mime_type in IMAGE_TYPES:
        return MediaKind.IMAGE
    if mime_type in VIDEO_TYPES:
        return MediaKind.VIDEO
    if mime_type in DOCUMENT_TYPES:
        return MediaKind.DOCUMENT
    return None


def allowed_formats(purpose: MediaPurpose) -> str:
    """Что можно загрузить для назначения: «JPEG, PNG, WebP, HEIC» — для текста ошибки."""
    kinds = {kind for (target, kind) in MAX_BYTES if target is purpose}
    return ", ".join(dict.fromkeys(name for mime, name in FORMATS if kind_of(mime) in kinds))


def upload_rule(purpose: MediaPurpose, mime_type: str, size_bytes: int) -> UploadRule:
    """Можно ли загрузить такой файл и как: одним PUT или частями."""
    if purpose not in MVP_PURPOSES:
        raise MediaPurposeNotAvailableError(purpose=purpose.value)
    kind = kind_of(mime_type)
    max_bytes = MAX_BYTES.get((purpose, kind)) if kind is not None else None
    if kind is None or max_bytes is None:
        # видео для аватара так же нельзя, как и незнакомый тип: в тексте — что можно
        raise UnsupportedMediaTypeError(mime_type=mime_type, allowed=allowed_formats(purpose))
    if size_bytes > max_bytes:
        raise MediaTooLargeError(max_bytes=max_bytes, max_mb=max_bytes // MB)
    return UploadRule(
        kind=kind,
        max_bytes=max_bytes,
        multipart=kind is MediaKind.VIDEO and size_bytes > MULTIPART_THRESHOLD,
    )
