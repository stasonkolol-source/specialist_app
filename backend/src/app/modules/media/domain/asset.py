"""Медиафайл и его жизненный цикл (ARCHITECTURE §7.8, §7.9, §10, ADR-0007).

`pending_upload → uploaded → processing → ready / failed / rejected`; `deleted` — мягкое
удаление из любого состояния. Файл загружает клиент прямо в хранилище (presigned PUT или
multipart), `complete` проверяет его HEAD-запросом и переводит в `uploaded`: в той же
транзакции уходит `MediaUploaded`, по нему воркер `media` обрабатывает файл (шаг 2.2).
Недогруженный файл через сутки убирает `media.cleanup_orphans` (статус `failed`).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.modules.media.domain.policy import MediaKind, MediaPurpose
from app.modules.media.errors import MediaStateError
from app.platform.contracts.events.media import MediaUploaded
from app.platform.kernel.aggregate import AggregateRoot
from app.platform.kernel.ids import MediaId, UserId


class MediaStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    REJECTED = "rejected"
    DELETED = "deleted"


class ModerationStatus(StrEnum):
    """Итог модерации файла (шаг 2.2 и 2.6); до обработки — `pending`."""

    PENDING = "pending"
    APPROVED = "approved"
    FLAGGED = "flagged"
    REJECTED = "rejected"


class FailureReason(StrEnum):
    ABANDONED = "abandoned"
    """Загрузку начали и не завершили за сутки (media.cleanup_orphans)."""
    MISMATCH = "mismatch"
    """В хранилище не тот файл: размер или тип отличаются от заявленных."""


INCOMING_BUCKET = "incoming"
"""Сырые загрузки: приватный бакет, lifecycle чистит его через 2 дня (ADR-0007)."""

AFTER_UPLOAD = frozenset(
    {MediaStatus.UPLOADED, MediaStatus.PROCESSING, MediaStatus.READY, MediaStatus.REJECTED}
)
"""Файл уже загружен: повторный `complete` ничего не меняет."""


@dataclass(eq=False, kw_only=True)
class MediaAsset(AggregateRoot):
    id: MediaId
    owner_id: UserId
    kind: MediaKind
    purpose: MediaPurpose
    status: MediaStatus
    bucket: str
    object_key: str
    mime_type: str
    size_bytes: int
    """Заявленный размер: подписан в presigned PUT, после загрузки сверяется HEAD-ом."""
    created_at: datetime
    upload_id: str | None = None
    """Id multipart-загрузки в хранилище (видео больше MULTIPART_THRESHOLD); иначе None."""
    etag: str | None = None
    """ETag оригинала после complete: presigned PUT живёт ещё до 10 минут, и обработка (2.2)
    должна читать тот файл, который сверили, а не подменённый позже."""
    uploaded_at: datetime | None = None
    failure_reason: FailureReason | None = None
    moderation_status: ModerationStatus = ModerationStatus.PENDING
    deleted_at: datetime | None = None

    @classmethod
    def start(
        cls,
        *,
        media_id: MediaId,
        owner_id: UserId,
        kind: MediaKind,
        purpose: MediaPurpose,
        mime_type: str,
        size_bytes: int,
        now: datetime,
        upload_id: str | None = None,
    ) -> MediaAsset:
        return cls(
            id=media_id,
            owner_id=owner_id,
            kind=kind,
            purpose=purpose,
            status=MediaStatus.PENDING_UPLOAD,
            bucket=INCOMING_BUCKET,
            object_key=object_key(purpose, media_id, now),
            mime_type=mime_type,
            size_bytes=size_bytes,
            created_at=now,
            upload_id=upload_id,
        )

    @property
    def multipart(self) -> bool:
        return self.upload_id is not None

    @property
    def uploaded(self) -> bool:
        return self.status in AFTER_UPLOAD

    def ensure_pending(self) -> None:
        """Ссылки на загрузку выдаются только до `complete`."""
        if self.status is not MediaStatus.PENDING_UPLOAD:
            raise MediaStateError(media_status=self.status.value)

    def complete(self, *, size_bytes: int, mime_type: str | None, etag: str, now: datetime) -> None:
        """Файл в хранилище совпал с заявленным: `uploaded` и событие для обработки.

        Не тот размер или тип — `failed` (mismatch): presigned PUT подписан на размер и тип,
        так что расхождение значит чужой или испорченный объект. Повтор после загрузки —
        без изменений (ответ на первый `complete` мог потеряться).
        """
        if self.uploaded:
            return
        self.ensure_pending()
        if size_bytes != self.size_bytes or (mime_type and mime_type != self.mime_type):
            self.status = MediaStatus.FAILED
            self.failure_reason = FailureReason.MISMATCH
            return
        self.status = MediaStatus.UPLOADED
        self.etag = etag
        self.uploaded_at = now
        self._record(
            MediaUploaded(
                media_id=self.id,
                owner_id=self.owner_id,
                kind=self.kind.value,
                purpose=self.purpose.value,
                occurred_at=now,
            )
        )

    def abandon(self) -> None:
        """Загрузку не завершили за сутки (media.cleanup_orphans)."""
        self.ensure_pending()
        self.status = MediaStatus.FAILED
        self.failure_reason = FailureReason.ABANDONED

    def delete(self, *, now: datetime) -> bool:
        """Мягкое удаление; повтор — без изменений. True — удалили сейчас."""
        if self.status is MediaStatus.DELETED:
            return False
        self.status = MediaStatus.DELETED
        self.deleted_at = now
        return True


def object_key(purpose: MediaPurpose, media_id: MediaId, now: datetime) -> str:
    """`{purpose}/{yyyy}/{mm}/{id}/original` (ARCHITECTURE §7.8): ключ не выбирает клиент."""
    return f"{purpose.value}/{now:%Y}/{now:%m}/{media_id}/original"
