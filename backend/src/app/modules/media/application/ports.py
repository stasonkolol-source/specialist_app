"""Порты модуля media (ADR-0020 §5): хранилище файлов — StoragePort платформы."""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Protocol

from app.modules.media.application.dto import (
    DeleteObjectsPayload,
    DiscardMediaPayload,
    HideVariantsPayload,
    ProcessedImage,
    ProcessedVideo,
)
from app.modules.media.domain.asset import FailureReason, MediaAsset
from app.modules.media.domain.policy import MediaKind
from app.platform.contracts.events.media import MediaUploaded
from app.platform.kernel.ids import MediaId, UserId
from app.platform.queue.port import TaskRef
from app.platform.storage.port import Bucket

PROCESS_MEDIA = TaskRef("media.process", MediaUploaded, queue="media")
"""Обработка загруженного файла в worker-media (шаг 2.2): варианты, EXIF, модерация."""

DELETE_OBJECTS = TaskRef("media.delete_objects", DeleteObjectsPayload)
"""Убрать из хранилища незавершённую загрузку или не тот файл: внешняя запись — задачей
после commit (ADR-0020 §3), с повтором при сбое хранилища."""


HIDE_VARIANTS = TaskRef("media.hide_variants", HideVariantsPayload)
"""Снять удалённый файл с публикации: варианты — в приватный бакет до очистки (§10.5)."""

DISCARD_MEDIA = TaskRef("media.discard_media", DiscardMediaPayload)
"""Удалить файл, который убрали из портфолио или сменили на фото профиля: ставится в транзакции
модуля выше по DAG — файл удаляется, только если его запись прошла, и с повтором при сбое."""


class UnprocessableMediaError(Exception):
    """Обработка не принимает файл: причина — в `reason` (не картинка, бомба, не читается)."""

    def __init__(self, reason: FailureReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class ProcessingCrashedError(Exception):
    """Обработка упала не по вине файла: рестарт воркера, OOM-kill, таймаут, наша ошибка.
    Задача повторится; после MAX_ATTEMPTS запусков файл получает `rejected`."""


class ImageProcessor(Protocol):
    async def process(self, data: bytes) -> ProcessedImage:
        """Варианты WebP без метаданных и ThumbHash. Файл не подходит —
        UnprocessableMediaError; сбой самой обработки — ProcessingCrashedError."""
        ...


class VideoProcessor(Protocol):
    async def process(
        self, bucket: Bucket, key: str, *, max_bytes: int, etag: str | None
    ) -> ProcessedVideo:
        """Скачать ролик потоком и перекодировать; ошибки — как у ImageProcessor, хранилище —
        StorageRejectedError, как у StoragePort.get."""
        ...


class UploadQuota(Protocol):
    async def charge(self, owner_id: UserId, size_bytes: int) -> None:
        """Списать загрузку из суточной квоты (1 GB, ARCHITECTURE §13.3); сверх неё —
        RateLimitedError. Вызывается только за принятый файл: отказ квоту не тратит."""
        ...


class MediaQuery(Protocol):
    async def asset(self, owner_id: UserId, media_id: MediaId) -> MediaAsset | None:
        """Файл владельца без блокировки; чужой, удалённый или несуществующий — None."""
        ...

    async def asset_by_id(self, media_id: MediaId) -> MediaAsset | None:
        """Файл в любом статусе, без проверки владельца — для задач системы."""
        ...

    async def assets(self, media_ids: Collection[MediaId]) -> list[MediaAsset]:
        """Неудалённые файлы по id — для показа в других модулях (фасад MediaApi)."""
        ...

    async def stuck(
        self,
        uploaded_before: datetime,
        uploaded_after: datetime,
        *,
        kinds: Collection[MediaKind],
        limit: int,
    ) -> Sequence[MediaAsset]:
        """Файлы этих видов, загруженные в этом окне и всё ещё не обработанные."""
        ...

    async def unhidden(self, deleted_before: datetime, *, limit: int) -> Sequence[MediaAsset]:
        """Удалённые файлы публичных назначений, чьи варианты ещё не спрятаны в private."""
        ...


class MediaRepository(Protocol):
    async def add(self, asset: MediaAsset) -> None:
        """Новый файл (`pending_upload`). Нужен активный UoW."""
        ...

    async def get_for_update(self, owner_id: UserId, media_id: MediaId) -> MediaAsset:
        """Файл владельца со строкой под блокировкой — для перехода статуса; чужой или
        удалённый — MediaNotFoundError. Нужен активный UoW."""
        ...

    async def get_by_id_for_update(self, media_id: MediaId) -> MediaAsset:
        """Файл в любом статусе под блокировкой — для задач системы. Нужен активный UoW."""
        ...

    async def save(self, asset: MediaAsset) -> None: ...

    async def pending_before(self, before: datetime, *, limit: int) -> Sequence[MediaAsset]:
        """Незавершённые загрузки старше `before`, под блокировкой без ожидания (SKIP LOCKED)."""
        ...

    async def deleted_before(
        self, before: datetime, *, now: datetime, limit: int
    ) -> Sequence[MediaAsset]:
        """Удалённые раньше `before`, чьи объекты ещё не стёрты и чей legal hold к `now`
        истёк или не ставился (SKIP LOCKED)."""
        ...
