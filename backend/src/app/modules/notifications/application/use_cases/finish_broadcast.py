"""Завершить разобранную рассылку (задача `notifications.finish_broadcast`, 2.7b).

Аудитория разобрана, но доставки могут ждать конца тихих часов получателей или паузы
лимитера: рассылка остаётся «идёт», пока есть ждущие, и её можно отменить. Задача проверяет
раз в BROADCAST_POLL; зависшие доставки через сутки закрывает `notifications.expire_stale`.
"""

from dataclasses import dataclass

from app.modules.notifications.application.ports import (
    BROADCAST_POLL,
    FINISH_BROADCAST,
    BroadcastPayload,
    BroadcastQuery,
    BroadcastRepository,
)
from app.modules.notifications.domain.broadcast import BroadcastId, BroadcastStatus
from app.modules.notifications.domain.catalog import Priority
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.queue.port import JobQueue


@dataclass(frozen=True, slots=True, kw_only=True)
class FinishBroadcastCommand:
    broadcast_id: BroadcastId


class FinishBroadcast:
    def __init__(
        self,
        uow: UnitOfWork,
        broadcasts: BroadcastRepository,
        query: BroadcastQuery,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._broadcasts, self._query = uow, broadcasts, query
        self._queue, self._clock = queue, clock

    async def __call__(self, cmd: FinishBroadcastCommand) -> BroadcastStatus:
        # после разбора аудитории новых доставок нет: ждущих только убывает
        pending = await self._query.pending(cmd.broadcast_id)
        now = self._clock.now()
        async with self._uow:
            broadcast = await self._broadcasts.get_for_update(cmd.broadcast_id)
            if broadcast.status is not BroadcastStatus.SENDING:
                return broadcast.status
            if pending:
                await self._queue.enqueue(
                    FINISH_BROADCAST,
                    BroadcastPayload(broadcast_id=broadcast.id),
                    dedup_key=str(broadcast.id),
                    not_before=now + BROADCAST_POLL,
                    priority=Priority.P4.job_priority,
                )
                return broadcast.status
            broadcast.finish(now)
            await self._broadcasts.save(broadcast)
        return broadcast.status
