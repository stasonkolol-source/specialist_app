"""Отменить рассылку (DEVELOPMENT_PLAN 2.7b): черновик, запланированную или идущую.

В одной транзакции со строкой рассылки (она заблокирована — пачка разбора аудитории ждёт или
уже записана): статус `cancelled`, ждущие доставки — `suppressed` (`cancelled`). Их задачи
отправки, придя к сроку, видят доставку не в `queued` и ничего не шлют; следующая задача разбора
аудитории видит отмену и не ставит новых. Уже отправленное не отзывается. Отмена — в audit_log.
"""

from dataclasses import dataclass

from app.modules.notifications.application.ports import (
    BroadcastRepository,
    NotificationRepository,
)
from app.modules.notifications.domain.broadcast import BroadcastId, dedupe_prefix
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId

CANCELLED = "cancelled"
"""Причина `suppressed` у доставок отменённой рассылки."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelBroadcastCommand:
    staff_id: UserId
    broadcast_id: BroadcastId


class CancelBroadcast:
    def __init__(
        self,
        uow: UnitOfWork,
        broadcasts: BroadcastRepository,
        notifications: NotificationRepository,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._uow, self._broadcasts, self._notifications = uow, broadcasts, notifications
        self._audit, self._clock = audit, clock

    async def __call__(self, cmd: CancelBroadcastCommand) -> int:
        """Сколько ждущих доставок погашено."""
        now = self._clock.now()
        async with self._uow:
            broadcast = await self._broadcasts.get_for_update(cmd.broadcast_id)
            previous = broadcast.status
            broadcast.cancel(now)
            await self._broadcasts.save(broadcast)
            suppressed = await self._notifications.suppress_queued(
                dedupe_prefix(broadcast.id), error=CANCELLED, now=now
            )
            await self._audit.record(
                AuditEntry(
                    action="notifications.broadcast.cancelled",
                    actor_kind=ActorKind.STAFF,
                    actor_id=cmd.staff_id,
                    entity_type="notifications.broadcast",
                    entity_id=broadcast.id,
                    changes={"from": previous.value, "suppressed": suppressed},
                )
            )
        return suppressed
