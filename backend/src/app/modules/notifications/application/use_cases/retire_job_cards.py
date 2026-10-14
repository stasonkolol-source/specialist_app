"""Заявка больше не принимает отклики — карточки B1 гасят кнопки (DEVELOPMENT_PLAN 5.7,
ARCHITECTURE §11.3).

Подписчики JobClosed, JobExpired и ResponseAccepted (клиент выбрал исполнителя): карточки
`job.matched:<заявка>:*`, которые ещё ждут конца тихих часов, не уходят (`suppressed`,
`job_closed`); на каждую отправленную ставится `notifications.retire_card` — правка кнопок идёт
через тот же лимитер, что и отправка, и не задерживает обработчик события сотнями вызовов Bot API.
Клиенту «Пока никто не откликнулся» (`job.no_responses:<заявка>`), ждущее утра, — тоже не уходит:
заявка закрыта, истекла или исполнитель выбран.
"""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.notifications.application.ports import (
    NO_RESPONSES_PREFIX,
    RETIRE_CARD,
    NotificationQuery,
    NotificationRepository,
    RetireCardPayload,
)
from app.modules.notifications.domain.catalog import CATALOG, NotificationType
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.queue.port import JobQueue

CLOSED: Final = "job_closed"
"""Причина `suppressed`: заявку закрыли, пока карточка ждала утра."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RetireJobCardsCommand:
    job_id: UUID


class RetireJobCards:
    def __init__(
        self,
        uow: UnitOfWork,
        notifications: NotificationRepository,
        query: NotificationQuery,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._notifications, self._query = uow, notifications, query
        self._queue, self._clock = queue, clock

    async def __call__(self, cmd: RetireJobCardsCommand) -> int:
        """Сколько отправленных карточек гасит."""
        prefix = f"{NotificationType.JOB_MATCHED}:{cmd.job_id}:"
        sent = await self._query.sent_with_prefix(prefix)
        priority = CATALOG[NotificationType.JOB_MATCHED].priority.job_priority
        now = self._clock.now()
        async with self._uow:
            await self._notifications.suppress_queued(prefix, error=CLOSED, now=now)
            await self._notifications.suppress_queued(
                f"{NO_RESPONSES_PREFIX}{cmd.job_id}", error=CLOSED, now=now
            )
            for delivery_id in sent:
                await self._queue.enqueue(
                    RETIRE_CARD,
                    RetireCardPayload(delivery_id=delivery_id),
                    dedup_key=str(delivery_id),
                    priority=priority,
                )
        return len(sent)
