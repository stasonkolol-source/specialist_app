"""Пересобрать отмеченные профили read-model (задача `search.flush_index`, 4.1).

Пачка — одна транзакция: взять отметки (SKIP LOCKED), собрать строки через фасады, записать
и удалить, снять отметки. Осталось ещё — задача ставит себя снова. Профиль автора со срочной
санкцией пересоберётся в её конце (`search.reindex_profiles` с not_before). Лаг от события
до строки уходит в метрику после commit.
"""

from dataclasses import dataclass
from typing import Final

import structlog

from app.modules.search.application.ports import (
    FLUSH_INDEX,
    REINDEX_PROFILES,
    FlushPayload,
    IndexMetrics,
    PendingProfiles,
    ReindexPayload,
    SpecialistIndex,
)
from app.modules.search.application.projection import SpecialistProjection
from app.modules.search.application.use_cases.mark_profiles import FLUSH_KEY
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.queue.port import JobQueue

log = structlog.get_logger(__name__)

BATCH: Final = 200
"""Профилей за транзакцию: фасады отвечают на пачку несколькими запросами."""


@dataclass(frozen=True, slots=True, kw_only=True)
class FlushIndexCommand:
    limit: int = BATCH


@dataclass(frozen=True, slots=True, kw_only=True)
class FlushReport:
    indexed: int
    removed: int
    more: bool
    """Отметки ещё остались: задача поставлена снова."""


class FlushIndex:
    def __init__(
        self,
        uow: UnitOfWork,
        pending: PendingProfiles,
        index: SpecialistIndex,
        projection: SpecialistProjection,
        queue: JobQueue,
        metrics: IndexMetrics,
        clock: Clock,
    ) -> None:
        self._uow, self._pending, self._index = uow, pending, index
        self._projection, self._queue = projection, queue
        self._metrics, self._clock = metrics, clock

    async def __call__(self, cmd: FlushIndexCommand) -> FlushReport:
        async with self._uow:
            taken = await self._pending.take(limit=cmd.limit)
            if not taken:
                return FlushReport(indexed=0, removed=0, more=False)
            ids = [item.profile_id for item in taken]
            built = await self._projection.build(ids)
            await self._index.upsert(built.entries)
            await self._index.delete(built.removed)
            await self._pending.clear(ids)
            for until, later in built.reindex_at.items():
                await self._queue.enqueue(
                    REINDEX_PROFILES,
                    ReindexPayload(profile_ids=tuple(later)),
                    not_before=until,
                )
            more = len(taken) == cmd.limit
            if more:
                await self._queue.enqueue(FLUSH_INDEX, FlushPayload(), dedup_key=FLUSH_KEY)
        now = self._clock.now()
        for item in taken:
            if item.occurred_at is not None:
                self._metrics.observe_lag((now - item.occurred_at).total_seconds())
        return FlushReport(indexed=len(built.entries), removed=len(built.removed), more=more)
