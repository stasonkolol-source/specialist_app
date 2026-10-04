"""Начать рассылку (DEVELOPMENT_PLAN 2.7b): сейчас или в назначенное время.

Сам разбор аудитории — задача `notifications.fan_out_broadcast` в очереди `notifications` с
приоритетом рассылки (P4, ниже задач-подписчиков): тысячи получателей не задерживают сообщения
чата и отклики. Старт пишется в audit_log от имени сотрудника.
"""

from dataclasses import dataclass
from datetime import datetime

from app.modules.notifications.application.ports import (
    FAN_OUT_BROADCAST,
    BroadcastPayload,
    BroadcastRepository,
)
from app.modules.notifications.domain.broadcast import BroadcastId, BroadcastStatus
from app.modules.notifications.domain.catalog import Priority
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId
from app.platform.queue.port import JobQueue


@dataclass(frozen=True, slots=True, kw_only=True)
class StartBroadcastCommand:
    staff_id: UserId
    broadcast_id: BroadcastId
    at: datetime | None = None
    """Начать не раньше; None или прошлое — сейчас."""


class StartBroadcast:
    def __init__(
        self,
        uow: UnitOfWork,
        broadcasts: BroadcastRepository,
        queue: JobQueue,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._uow, self._broadcasts, self._queue = uow, broadcasts, queue
        self._audit, self._clock = audit, clock

    async def __call__(self, cmd: StartBroadcastCommand) -> BroadcastStatus:
        now = self._clock.now()
        async with self._uow:
            broadcast = await self._broadcasts.get_for_update(cmd.broadcast_id)
            broadcast.start(now, cmd.at)
            await self._broadcasts.save(broadcast)
            await self._queue.enqueue(
                FAN_OUT_BROADCAST,
                BroadcastPayload(broadcast_id=broadcast.id),
                dedup_key=f"{broadcast.id}:start",
                not_before=broadcast.starts_at if broadcast.starts_at != now else None,
                priority=Priority.P4.job_priority,
            )
            await self._audit.record(
                AuditEntry(
                    action="notifications.broadcast.started",
                    actor_kind=ActorKind.STAFF,
                    actor_id=cmd.staff_id,
                    entity_type="notifications.broadcast",
                    entity_id=broadcast.id,
                    changes={
                        "status": broadcast.status.value,
                        "starts_at": broadcast.starts_at.isoformat()
                        if broadcast.starts_at
                        else None,
                    },
                )
            )
        return broadcast.status
