"""Страховка: доставки, зависшие в `queued` (периодическая `notifications.expire_stale`).

Доставка уходит сразу или к сроку, а её судьбу решает задача `notifications.send`. Если
задачу потеряли (воркер упал за пределами повторов, ошибка, не учтённая ни одним путём),
доставка осталась бы `queued` навсегда и выглядела бы «ещё в пути». Через сутки после срока
она становится `failed` (`stale`): сообщение сутки спустя уже не нужно, а статус честный.
Индекс `ix_deliveries_not_before` (WHERE status = 'queued') делает проход дешёвым.
"""

from dataclasses import dataclass
from datetime import timedelta

import structlog

from app.modules.notifications.application.ports import NotificationRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

log = structlog.get_logger(__name__)

STALE_AFTER = timedelta(days=1)
CHUNK = 500
"""Доставок за проход: больше — в следующий час."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpireStaleDeliveriesCommand:
    limit: int = CHUNK


class ExpireStaleDeliveries:
    def __init__(
        self, uow: UnitOfWork, notifications: NotificationRepository, clock: Clock
    ) -> None:
        self._uow, self._notifications, self._clock = uow, notifications, clock

    async def __call__(self, cmd: ExpireStaleDeliveriesCommand) -> int:
        now = self._clock.now()
        async with self._uow:
            expired = await self._notifications.expire_stale(
                due_before=now - STALE_AFTER, limit=cmd.limit
            )
        if expired:
            log.warning("notification_deliveries_stale", count=expired)
        return expired
