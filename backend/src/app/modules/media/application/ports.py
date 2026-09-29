"""Порты модуля media (ADR-0020 §5): хранилище файлов — StoragePort платформы."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.modules.media.application.dto import DeleteObjectPayload
from app.modules.media.domain.asset import MediaAsset
from app.platform.contracts.events.media import MediaUploaded
from app.platform.kernel.ids import MediaId, UserId
from app.platform.queue.port import TaskRef

PROCESS_MEDIA = TaskRef("media.process", MediaUploaded, queue="media")
"""Обработка загруженного файла в worker-media (шаг 2.2): варианты, EXIF, модерация."""

DELETE_OBJECT = TaskRef("media.delete_object", DeleteObjectPayload)
"""Убрать из хранилища незавершённую загрузку или не тот файл: внешняя запись — задачей
после commit (ADR-0020 §3), с повтором при сбое хранилища."""


class UploadQuota(Protocol):
    async def charge(self, owner_id: UserId, size_bytes: int) -> None:
        """Списать загрузку из суточной квоты (1 GB, ARCHITECTURE §13.3); сверх неё —
        RateLimitedError. Вызывается только за принятый файл: отказ квоту не тратит."""
        ...


class MediaQuery(Protocol):
    async def asset(self, owner_id: UserId, media_id: MediaId) -> MediaAsset | None:
        """Файл владельца без блокировки; чужой, удалённый или несуществующий — None."""
        ...


class MediaRepository(Protocol):
    async def add(self, asset: MediaAsset) -> None:
        """Новый файл (`pending_upload`). Нужен активный UoW."""
        ...

    async def get_for_update(self, owner_id: UserId, media_id: MediaId) -> MediaAsset:
        """Файл владельца со строкой под блокировкой — для перехода статуса; чужой или
        удалённый — MediaNotFoundError. Нужен активный UoW."""
        ...

    async def save(self, asset: MediaAsset) -> None: ...

    async def pending_before(self, before: datetime, *, limit: int) -> Sequence[MediaAsset]:
        """Незавершённые загрузки старше `before`, под блокировкой без ожидания (SKIP LOCKED)."""
        ...
