"""Ответы модуля media (ARCHITECTURE §10.2)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from app.modules.media.domain.asset import MediaStatus, ModerationStatus
from app.modules.media.domain.policy import MediaKind, MediaPurpose
from app.platform.kernel.ids import MediaId


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
    """Оригинал для владельца (presigned GET на 5 минут), пока нет вариантов (шаг 2.2)."""
