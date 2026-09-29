"""Схемы HTTP media (ARCHITECTURE §8.5, §10.2)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.media.domain.asset import MediaStatus, ModerationStatus
from app.modules.media.domain.policy import MB, MediaKind, MediaPurpose
from app.platform.storage.port import MAX_PARTS

MAX_UPLOAD_BYTES = 200 * MB
"""Самый большой лимит назначения (видео портфолио); точный — по назначению и типу."""


class UploadIn(BaseModel):
    purpose: MediaPurpose
    mime_type: str = Field(min_length=3, max_length=100)
    """Тип файла; на Android HEIC приходит без типа — клиент ставит его по расширению."""
    size_bytes: int = Field(ge=1, le=MAX_UPLOAD_BYTES)


class SignedPartOut(BaseModel):
    part_number: int | None
    """Номер части multipart; null — файл целиком одним PUT."""
    url: str
    headers: dict[str, str]
    """Отправить как есть: подпись учитывает Content-Type."""


class UploadOut(BaseModel):
    media_id: UUID
    multipart: bool
    part_size: int | None
    """Размер части (последняя — остаток); null у загрузки одним PUT."""
    parts: list[SignedPartOut]
    expires_at: datetime
    """Ссылки живут 10 минут; истекли — POST /media/uploads/{id}/parts."""


class PartsIn(BaseModel):
    part_numbers: list[int] | None = Field(default=None, max_length=MAX_PARTS)
    """Какие части переподписать; null — все (или файл целиком)."""


class UploadedPartIn(BaseModel):
    part_number: int = Field(ge=1, le=MAX_PARTS)
    etag: str = Field(min_length=1, max_length=128)
    """ETag из ответа хранилища на PUT части (CORS бакета отдаёт заголовок ETag)."""


class CompleteIn(BaseModel):
    parts: list[UploadedPartIn] = Field(default_factory=list, max_length=MAX_PARTS)
    """ETag частей multipart; у загрузки одним PUT — пусто."""


class MediaOut(BaseModel):
    id: UUID
    kind: MediaKind
    purpose: MediaPurpose
    status: MediaStatus
    mime_type: str
    size_bytes: int
    moderation_status: ModerationStatus
    created_at: datetime
    uploaded_at: datetime | None
    preview_url: str | None
    """Оригинал для владельца на 5 минут, пока нет вариантов (обработка — шаг 2.2)."""
