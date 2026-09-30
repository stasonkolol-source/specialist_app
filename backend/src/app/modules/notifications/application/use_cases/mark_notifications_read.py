"""Отметить уведомления центра прочитанными (`POST /me/notifications/read`, S42).

Только свои: чужие id молча не находятся. Повтор идемпотентен — прочитанное остаётся с
первым временем прочтения.
"""

from collections.abc import Collection
from dataclasses import dataclass

from app.modules.notifications.application.ports import NotificationQuery, NotificationRepository
from app.modules.notifications.domain.notification import NotificationId
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class MarkNotificationsReadCommand:
    user_id: UserId
    ids: Collection[NotificationId] | None
    """None — все."""


class MarkNotificationsRead:
    def __init__(
        self,
        uow: UnitOfWork,
        notifications: NotificationRepository,
        query: NotificationQuery,
        clock: Clock,
    ) -> None:
        self._uow, self._notifications, self._query, self._clock = uow, notifications, query, clock

    async def __call__(self, cmd: MarkNotificationsReadCommand) -> int:
        """Сколько непрочитанных осталось — для бейджа."""
        async with self._uow:
            await self._notifications.mark_read(cmd.user_id, cmd.ids, now=self._clock.now())
        return await self._query.unread(cmd.user_id)
