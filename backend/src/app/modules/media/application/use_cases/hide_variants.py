"""Снять удалённый файл с публикации (задача `media.hide_variants`, ARCHITECTURE §10.5).

Публичные варианты удалённого файла переносятся из media в private (копия на стороне
хранилища, потом удаление): по старой ссылке их больше не открыть, а 30 дней до очистки они
лежат в приватном бакете. Берутся все возможные ключи — прерванная обработка могла оставить
часть. Готово — `hidden_at`; не вышло (права на бакет, сбой) — повтор задачи, а после него
страховка `media.hide_deleted` ставит её снова.
"""

from dataclasses import dataclass
from datetime import timedelta

import structlog

from app.modules.media.application.dto import HideVariantsPayload
from app.modules.media.application.ports import HIDE_VARIANTS, MediaQuery, MediaRepository
from app.modules.media.domain.asset import MEDIA_BUCKET, MediaStatus, variant_bucket
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import MediaId
from app.platform.queue.port import JobQueue
from app.platform.storage.port import Bucket, StoragePort

log = structlog.get_logger(__name__)

HIDE_AFTER = timedelta(minutes=15)
"""Страховка берёт файлы, удалённые раньше: свежие скрывает задача, поставленная при удалении."""
CHUNK = 50


@dataclass(frozen=True, slots=True, kw_only=True)
class HideVariantsCommand:
    media_id: MediaId


class HideVariants:
    def __init__(
        self,
        uow: UnitOfWork,
        assets: MediaRepository,
        query: MediaQuery,
        storage: StoragePort,
        clock: Clock,
    ) -> None:
        self._uow, self._assets, self._query = uow, assets, query
        self._storage, self._clock = storage, clock

    async def __call__(self, cmd: HideVariantsCommand) -> None:
        asset = await self._query.asset_by_id(cmd.media_id)
        if (
            asset is None
            or asset.status is not MediaStatus.DELETED
            or asset.hidden_at is not None
            or asset.purged_at is not None
        ):
            return
        if variant_bucket(asset.purpose) == MEDIA_BUCKET:
            for key in asset.variant_keys():  # уже перенесённого в media нет — пропуск
                if await self._storage.copy(Bucket.MEDIA, key, to=Bucket.PRIVATE):
                    await self._storage.delete(Bucket.MEDIA, key)
        async with self._uow:
            asset = await self._assets.get_by_id_for_update(cmd.media_id)
            if asset.status is MediaStatus.DELETED and asset.hidden_at is None:
                asset.hide(now=self._clock.now())
                await self._assets.save(asset)
        log.info("media_variants_hidden", media_id=str(cmd.media_id))


@dataclass(frozen=True, slots=True, kw_only=True)
class HideDeletedCommand:
    limit: int = CHUNK


class HideDeleted:
    """Страховка (periodic `media.hide_deleted`): удалённые, но всё ещё публичные файлы."""

    def __init__(self, uow: UnitOfWork, query: MediaQuery, queue: JobQueue, clock: Clock) -> None:
        self._uow, self._query, self._queue, self._clock = uow, query, queue, clock

    async def __call__(self, cmd: HideDeletedCommand) -> int:
        assets = await self._query.unhidden(self._clock.now() - HIDE_AFTER, limit=cmd.limit)
        if not assets:
            return 0
        async with self._uow:
            for asset in assets:
                await self._queue.enqueue(
                    HIDE_VARIANTS,
                    HideVariantsPayload(media_id=asset.id, keys=asset.variant_keys()),
                    dedup_key=str(asset.id),
                )
        log.info("media_hide_retried", count=len(assets))
        return len(assets)
