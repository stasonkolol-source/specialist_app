"""Повторить зависшую обработку (periodic `media.retry_stuck`, ARCHITECTURE §10.3).

Задача `media.process` повторяется сама, но после исчерпанных повторов (хранилище лежало
дольше нескольких минут) или потерянной задачи файл остался бы `uploaded` или `processing`
навсегда. Раз в 15 минут такие файлы ставятся в обработку снова — первые сутки после
загрузки: фото — через 15 минут, ролик — через час (перекодирование само идёт до 15 минут,
и второй запуск поверх первого только тратил бы попытки). Кто завис дольше суток, получает
`rejected` (unreadable): честный отказ лучше вечного ожидания, а оригинал в incoming через
2 дня всё равно уберёт lifecycle.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType

import structlog

from app.modules.media.application.ports import (
    DELETE_OBJECTS,
    PROCESS_MEDIA,
    MediaQuery,
    MediaRepository,
)
from app.modules.media.application.uploads import delete_variants
from app.modules.media.domain.asset import TO_PROCESS, variant_bucket
from app.modules.media.domain.policy import MediaKind
from app.platform.contracts.events.media import MediaUploaded
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.queue.port import JobQueue

log = structlog.get_logger(__name__)

STUCK_AFTER: Mapping[MediaKind, timedelta] = MappingProxyType(
    {MediaKind.IMAGE: timedelta(minutes=15), MediaKind.VIDEO: timedelta(hours=1)}
)
"""Сколько после загрузки файл может честно обрабатываться (с очередью)."""
GIVE_UP_AFTER = timedelta(days=1)
CHUNK = 50
"""Постановок на транзакцию: каждая — savepoint (см. purge_deleted)."""
FAR_PAST = timedelta(days=3650)


@dataclass(frozen=True, slots=True, kw_only=True)
class RetryStuckCommand:
    limit: int = CHUNK


class RetryStuck:
    def __init__(
        self,
        uow: UnitOfWork,
        assets: MediaRepository,
        query: MediaQuery,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._assets, self._query = uow, assets, query
        self._queue, self._clock = queue, clock

    async def __call__(self, cmd: RetryStuckCommand) -> int:
        """Сколько файлов поставлено в обработку снова."""
        now = self._clock.now()
        await self._give_up(now, cmd.limit)
        stuck = [
            asset
            for kind, after in STUCK_AFTER.items()
            for asset in await self._query.stuck(
                now - after, now - GIVE_UP_AFTER, kinds=(kind,), limit=cmd.limit
            )
        ]
        if not stuck:
            return 0
        async with self._uow:
            for asset in stuck:
                event = MediaUploaded(
                    media_id=asset.id,
                    owner_id=asset.owner_id,
                    kind=asset.kind.value,
                    purpose=asset.purpose.value,
                    occurred_at=now,
                )
                await self._queue.enqueue(PROCESS_MEDIA, event, dedup_key=f"retry:{asset.id}")
        log.info("media_processing_retried", count=len(stuck))
        return len(stuck)

    async def _give_up(self, now: datetime, limit: int) -> None:
        hopeless = await self._query.stuck(
            now - GIVE_UP_AFTER, now - FAR_PAST, kinds=tuple(STUCK_AFTER), limit=limit
        )
        if not hopeless:
            return
        async with self._uow:
            for found in hopeless:
                asset = await self._assets.get_by_id_for_update(found.id)
                if asset.status not in TO_PROCESS:
                    continue
                asset.give_up(now=now)
                await self._assets.save(asset)
                await self._queue.enqueue(
                    DELETE_OBJECTS,
                    delete_variants(asset, variant_bucket(asset.purpose), with_original=True),
                    dedup_key=f"rejected:{asset.id}",
                )
        log.warning("media_processing_abandoned", count=len(hopeless))
