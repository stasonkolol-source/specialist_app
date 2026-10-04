"""Снять файл с публикации и вернуть (задачи `media.hide_variants` и `media.restore_variants`,
ARCHITECTURE §10.5; DEVELOPMENT_PLAN 6.7).

Публичные варианты удалённого или отклонённого модерацией файла переносятся из media в private
(копия на стороне хранилища, потом удаление): по старой ссылке CDN их больше не открыть, а до
очистки или решения модератора они лежат в приватном бакете. Берутся все возможные ключи —
прерванная обработка могла оставить часть. Готово — `hidden_at`; не вышло (права на бакет,
сбой) — повтор задачи, а после него страховка `media.hide_deleted` ставит её снова.

Модератор снял отказ — варианты возвращаются тем же способом, `hidden_at` очищается. Решение
могло смениться, пока объекты переносились: тогда задача ставит обратную, и последнее решение
побеждает.
"""

from dataclasses import dataclass
from datetime import timedelta

import structlog

from app.modules.media.application.dto import HideVariantsPayload
from app.modules.media.application.ports import (
    HIDE_VARIANTS,
    RESTORE_VARIANTS,
    MediaQuery,
    MediaRepository,
)
from app.modules.media.domain.asset import MEDIA_BUCKET, MediaAsset, MediaStatus, variant_bucket
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
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._assets, self._query = uow, assets, query
        self._storage, self._queue, self._clock = storage, queue, clock

    async def __call__(self, cmd: HideVariantsCommand) -> None:
        asset = await self._query.asset_by_id(cmd.media_id)
        if (
            asset is None
            or not asset.needs_hiding
            or asset.hidden_at is not None
            or asset.purged_at is not None
        ):
            return
        if variant_bucket(asset.purpose) == MEDIA_BUCKET:
            await _move(self._storage, asset, source=Bucket.MEDIA, target=Bucket.PRIVATE)
        async with self._uow:
            asset = await self._assets.get_by_id_for_update(cmd.media_id)
            if asset.needs_hiding and asset.hidden_at is None:
                asset.hide(now=self._clock.now())
                await self._assets.save(asset)
            elif not asset.needs_hiding:  # отказ сняли, пока переносили: вернуть варианты
                await self._queue_restore(asset)
        log.info("media_variants_hidden", media_id=str(cmd.media_id))

    async def _queue_restore(self, asset: MediaAsset) -> None:
        await self._queue.enqueue(
            RESTORE_VARIANTS,
            HideVariantsPayload(media_id=asset.id, keys=asset.variant_keys()),
            dedup_key=str(asset.id),
        )


class RestoreVariants:
    """Отказ модерации снят: варианты — из private обратно в публичный media. Не зависит от
    `hidden_at`: перенос мог пройти, а отметка — ещё нет; чего нет в private — пропуск."""

    def __init__(
        self,
        uow: UnitOfWork,
        assets: MediaRepository,
        query: MediaQuery,
        storage: StoragePort,
        queue: JobQueue,
    ) -> None:
        self._uow, self._assets, self._query = uow, assets, query
        self._storage, self._queue = storage, queue

    async def __call__(self, cmd: HideVariantsCommand) -> None:
        asset = await self._query.asset_by_id(cmd.media_id)
        if asset is None or asset.needs_hiding or asset.status is not MediaStatus.READY:
            return
        if variant_bucket(asset.purpose) == MEDIA_BUCKET:
            await _move(self._storage, asset, source=Bucket.PRIVATE, target=Bucket.MEDIA)
        async with self._uow:
            asset = await self._assets.get_by_id_for_update(cmd.media_id)
            if asset.needs_hiding:  # снова отклонили, пока возвращали: спрятать
                await self._queue.enqueue(
                    HIDE_VARIANTS,
                    HideVariantsPayload(media_id=asset.id, keys=asset.variant_keys()),
                    dedup_key=str(asset.id),
                )
            elif asset.hidden_at is not None:
                asset.show()
                await self._assets.save(asset)
        log.info("media_variants_restored", media_id=str(cmd.media_id))


async def _move(storage: StoragePort, asset: MediaAsset, *, source: Bucket, target: Bucket) -> None:
    for key in asset.variant_keys():  # уже перенесённого нет в источнике — пропуск
        if await storage.copy(source, key, to=target):
            await storage.delete(source, key)


@dataclass(frozen=True, slots=True, kw_only=True)
class HideDeletedCommand:
    limit: int = CHUNK


class HideDeleted:
    """Страховка (periodic `media.hide_deleted`): удалённые или отклонённые модерацией, но всё
    ещё публичные файлы."""

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
