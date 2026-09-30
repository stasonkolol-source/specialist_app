"""Медиафайл и его жизненный цикл (ARCHITECTURE §7.8, §7.9, §10, ADR-0007).

`pending_upload → uploaded → processing → ready / failed / rejected`; `deleted` — мягкое
удаление из любого состояния. Файл загружает клиент прямо в хранилище (presigned PUT или
multipart), `complete` проверяет его HEAD-запросом и переводит в `uploaded`: в той же
транзакции уходит `MediaUploaded`, по нему воркер `media` обрабатывает файл (шаг 2.2) —
`ready` с вариантами без EXIF или `rejected`, если это не картинка или бомба.
Недогруженный файл через сутки убирает `media.cleanup_orphans` (статус `failed`), объекты
удалённого — `media.purge_deleted` через 30 дней.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from app.modules.media.domain.policy import MediaKind, MediaPurpose
from app.modules.media.errors import MediaStateError
from app.platform.contracts.events.media import MediaReady, MediaRejected, MediaUploaded
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
    """Почему `failed` (загрузка) или `rejected` (обработка)."""

    ABANDONED = "abandoned"
    """Загрузку начали и не завершили за сутки (media.cleanup_orphans)."""
    MISMATCH = "mismatch"
    """В хранилище не тот файл: размер, тип или ETag отличаются от сверенных."""
    UNSUPPORTED = "unsupported"
    """По содержимому (magic bytes) это не картинка из allow-list."""
    TOO_MANY_PIXELS = "too_many_pixels"
    """Кадр больше предела пикселей: decompression bomb или сверхкрупный снимок."""
    UNREADABLE = "unreadable"
    """Файл не декодируется или пропал из хранилища."""
    TOO_LONG = "too_long"
    """Ролик длиннее минуты (ADR-0007: видео портфолио — до 60 с)."""


INCOMING_BUCKET = "incoming"
"""Сырые загрузки: приватный бакет, lifecycle чистит его через 2 дня (ADR-0007)."""
MEDIA_BUCKET = "media"
"""Обработанные варианты: публичный бакет за CDN, ключи неизменяемые (§10.4)."""
PRIVATE_BUCKET = "private"
"""Варианты непубличных назначений и удалённых файлов: только presigned GET."""


class VariantName(StrEnum):
    THUMB = "thumb"
    MD = "md"
    LG = "lg"
    VIDEO = "video"
    """Ролик MP4 H.264 720p; у видео thumb/md/lg — его постер."""


VARIANT_SIDES: Mapping[str, int] = MappingProxyType(
    {VariantName.THUMB: 320, VariantName.MD: 800, VariantName.LG: 1600}
)
"""WebP-варианты фото: длинная сторона в пикселях (§10.3). Оригинал после обработки не
храним: клиент уже уменьшает фото до ≈2048 px, а сырой файл несёт EXIF с GPS."""

PUBLIC_PURPOSES = frozenset({MediaPurpose.AVATAR, MediaPurpose.PORTFOLIO, MediaPurpose.JOB})
"""Что показывают всем: аватар, портфолио, фото заявки — варианты в публичном бакете media.
Сообщения, отзывы и документы (v1) — в private."""


def variant_bucket(purpose: MediaPurpose) -> str:
    return MEDIA_BUCKET if purpose in PUBLIC_PURPOSES else PRIVATE_BUCKET


PURGE_AFTER = timedelta(days=30)
"""Объекты удалённого пользователем файла живут ещё 30 дней (§10.5)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Variant:
    key: str
    width: int
    height: int


def variant_key(media_id: MediaId, name: str) -> str:
    """`m/{id}/{variant}.webp` (у ролика — `.mp4`) в бакете media: CDN отдаёт `cdn.<domain>/m/…`."""
    extension = "mp4" if name == VariantName.VIDEO else "webp"
    return f"m/{media_id}/{name}.{extension}"


AFTER_UPLOAD = frozenset(
    {MediaStatus.UPLOADED, MediaStatus.PROCESSING, MediaStatus.READY, MediaStatus.REJECTED}
)
"""Файл уже загружен: повторный `complete` ничего не меняет."""

TO_PROCESS = frozenset({MediaStatus.UPLOADED, MediaStatus.PROCESSING})
"""Обработку можно начать или продолжить (повтор задачи после сбоя)."""

MAX_ATTEMPTS = 3
"""Запусков обработки на файл: сбой не по вине файла (рестарт, OOM, таймаут) — повтор,
но не бесконечный — третий такой сбой отклоняет файл."""


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
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    """Длительность ролика; у фото — None."""
    placeholder: str | None = None
    """ThumbHash в base64: превью, пока грузится вариант."""
    sha256: bytes | None = None
    variants: Mapping[str, Variant] = field(default_factory=dict)
    processed_at: datetime | None = None
    attempts: int = 0
    """Сколько раз начиналась обработка."""
    deleted_at: datetime | None = None
    hidden_at: datetime | None = None
    """Варианты удалённого файла перенесены из публичного media в private."""
    purged_at: datetime | None = None

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

    def start_processing(self) -> bool:
        """`uploaded → processing` (или повтор после сбоя) и ещё одна попытка. False —
        обрабатывать нечего: файл уже готов, отклонён или удалён."""
        if self.status not in TO_PROCESS:
            return False
        self.status = MediaStatus.PROCESSING
        self.attempts += 1
        return True

    @property
    def out_of_attempts(self) -> bool:
        return self.attempts >= MAX_ATTEMPTS

    def release_attempt(self) -> bool:
        """Запуск сорвало хранилище, а не файл: попытка не считается. False — нечего
        возвращать (файл уже не обрабатывается или попыток не было)."""
        if self.status is not MediaStatus.PROCESSING or self.attempts == 0:
            return False
        self.attempts -= 1
        return True

    def give_up(self, *, now: datetime) -> None:
        """Обработка так и не удалась (сбои не по вине файла кончились попытками или файл
        завис на сутки): `rejected` (unreadable) — лучше честный отказ, чем вечное ожидание."""
        if self.status not in TO_PROCESS:
            raise MediaStateError(media_status=self.status.value)
        self.status = MediaStatus.PROCESSING
        self.reject(FailureReason.UNREADABLE, now=now)

    def hide(self, *, now: datetime) -> None:
        """Варианты удалённого файла перенесены в private (media.hide_variants)."""
        if self.status is not MediaStatus.DELETED:
            raise MediaStateError(media_status=self.status.value)
        self.hidden_at = now

    def ready(
        self,
        *,
        width: int,
        height: int,
        placeholder: str,
        sha256: bytes,
        variants: Mapping[str, Variant],
        now: datetime,
        duration_ms: int | None = None,
    ) -> None:
        """Варианты без метаданных лежат в бакете назначения: файл можно показывать."""
        self._ensure_processing()
        self.status = MediaStatus.READY
        self.width, self.height, self.duration_ms = width, height, duration_ms
        self.placeholder, self.sha256 = placeholder, sha256
        self.variants = dict(variants)
        self.processed_at = now
        self._record(
            MediaReady(
                media_id=self.id,
                owner_id=self.owner_id,
                kind=self.kind.value,
                purpose=self.purpose.value,
                occurred_at=now,
            )
        )

    def reject(self, reason: FailureReason, *, now: datetime) -> None:
        """Обработка не приняла файл: не картинка, бомба, не читается или подменён."""
        self._ensure_processing()
        self.status = MediaStatus.REJECTED
        self.failure_reason = reason
        self.processed_at = now
        self._record(
            MediaRejected(
                media_id=self.id,
                owner_id=self.owner_id,
                purpose=self.purpose.value,
                reason=reason.value,
                occurred_at=now,
            )
        )

    def variant_keys(self) -> tuple[str, ...]:
        """Все возможные ключи вариантов, а не только записанные: прерванная обработка
        могла оставить часть файлов, о которых запись не знает."""
        return tuple(variant_key(self.id, name) for name in VariantName)

    def objects(self) -> tuple[tuple[str, str], ...]:
        """Все объекты файла (бакет, ключ): оригинал и варианты — и в media, и в private:
        удалённый файл прячет варианты в private (media.hide_variants)."""
        return (
            (self.bucket, self.object_key),
            *(
                (bucket, key)
                for key in self.variant_keys()
                for bucket in (MEDIA_BUCKET, PRIVATE_BUCKET)
            ),
        )

    def purge(self, *, now: datetime) -> None:
        """Объекты удалённого файла удалены (media.purge_deleted); запись остаётся."""
        if self.status is not MediaStatus.DELETED:
            raise MediaStateError(media_status=self.status.value)
        self.purged_at = now

    def _ensure_processing(self) -> None:
        if self.status is not MediaStatus.PROCESSING:
            raise MediaStateError(media_status=self.status.value)

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
