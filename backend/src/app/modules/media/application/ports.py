"""Порты модуля media (ADR-0020 §5): хранилище файлов — StoragePort платформы."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.modules.media.domain.asset import MediaAsset
from app.platform.contracts.events.media import MediaUploaded
from app.platform.kernel.ids import MediaId, UserId
from app.platform.queue.port import TaskRef

PROCESS_MEDIA = TaskRef("media.process", MediaUploaded, queue="media")
"""Обработка загруженного файла в worker-media (шаг 2.2): варианты, EXIF, модерация."""


class MediaRepository(Protocol):
    async def add(self, asset: MediaAsset) -> None:
        """Новый файл (`pending_upload`). Нужен активный UoW."""
        ...

    async def get(self, owner_id: UserId, media_id: MediaId) -> MediaAsset:
        """Файл владельца; чужой или удалённый (`deleted`) — MediaNotFoundError."""
        ...

    async def get_for_update(self, owner_id: UserId, media_id: MediaId) -> MediaAsset:
        """То же со строкой под блокировкой — для перехода статуса. Нужен активный UoW."""
        ...

    async def save(self, asset: MediaAsset) -> None: ...

    async def pending_before(self, before: datetime, *, limit: int) -> Sequence[MediaAsset]:
        """Незавершённые загрузки старше `before`, под блокировкой без ожидания (SKIP LOCKED)."""
        ...
