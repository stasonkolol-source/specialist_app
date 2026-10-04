"""Ответы модуля media (ARCHITECTURE §10.2)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from app.modules.media.domain.asset import FailureReason, MediaStatus, ModerationStatus
from app.modules.media.domain.policy import MediaKind, MediaPurpose
from app.platform.kernel.ids import MediaId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class SignedPart:
    part_number: int | None
    """Номер части multipart; None — файл целиком одним PUT."""
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    """Заголовки, которые клиент отправляет как есть: подпись их учитывает."""


@dataclass(frozen=True, slots=True, kw_only=True)
class UploadPlan:
    media_id: MediaId
    multipart: bool
    part_size: int | None
    """Размер части multipart (последняя — остаток); None у загрузки одним PUT."""
    parts: tuple[SignedPart, ...]
    expires_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class VariantView:
    name: str
    url: str
    width: int
    height: int


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaView:
    id: MediaId
    kind: MediaKind
    purpose: MediaPurpose
    status: MediaStatus
    mime_type: str
    size_bytes: int
    moderation_status: ModerationStatus
    created_at: datetime
    uploaded_at: datetime | None
    preview_url: str | None
    """Оригинал для владельца (presigned GET на 5 минут), пока нет вариантов."""
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    placeholder: str | None = None
    """ThumbHash (base64) для мгновенного превью."""
    variants: tuple[VariantView, ...] = ()
    """WebP-варианты по возрастанию ширины — для srcset (у `ready`); у ролика — постер."""
    video: VariantView | None = None
    """MP4 готового ролика: в srcset ему не место, поэтому отдельно от вариантов."""
    failure_reason: FailureReason | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageVariant:
    name: str
    width: int
    height: int
    body: bytes


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessedImage:
    """Итог обработки фото: варианты WebP без метаданных и сведения об оригинале."""

    width: int
    height: int
    placeholder: str
    sha256: bytes
    phash: int
    """pHash кадра (64 бита без знака): поиск дубликатов портфолио у других аккаунтов."""
    variants: tuple[ImageVariant, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessedVideo:
    """Итог обработки ролика: MP4 H.264 720p без метаданных и кадр для постера."""

    width: int
    height: int
    duration_ms: int
    sha256: bytes
    video: bytes
    poster: bytes
    """Кадр PNG: из него конвейер фото делает постер (варианты и ThumbHash)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredRef:
    bucket: str
    key: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DeleteObjectsPayload:
    """Задача `media.delete_objects`: объекты файла, которые убрать из хранилища."""

    media_id: MediaId
    objects: tuple[StoredRef, ...]
    upload_id: str | None = None
    """Незавершённая multipart-загрузка первого объекта (оригинала): отменяется до удаления."""


@dataclass(frozen=True, slots=True, kw_only=True)
class HideVariantsPayload:
    """Задачи `media.hide_variants` (варианты удалённого или отклонённого файла — из media в
    private) и `media.restore_variants` (обратно)."""

    media_id: MediaId
    keys: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class DiscardMediaPayload:
    """Задача `media.discard_media`: файл, который модуль выше по DAG больше не показывает."""

    user_id: UserId
    """Владелец файла."""
    media_id: MediaId
