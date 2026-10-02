"""Поставить уведомление об откликах (`response.received`, ARCHITECTURE §11.3; DEVELOPMENT_PLAN
5.4): дебаунс окном. Первый отклик на заявку ставит задачу на конец окна; пока она ждёт,
следующие отклики ничего не ставят — замок очереди по заявке. Три отклика за пять минут —
одно уведомление «Новых откликов: 3».
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.notifications.application.ports import (
    NOTIFY_RESPONSES,
    RESPONSES_DEBOUNCE,
    ResponsesWindow,
)
from app.platform.db.port import UnitOfWork
from app.platform.queue.port import JobQueue


@dataclass(frozen=True, slots=True, kw_only=True)
class ScheduleResponsesNoticeCommand:
    job_id: UUID
    at: datetime
    """Когда пришёл отклик: окно закрывается через RESPONSES_DEBOUNCE после первого."""


class ScheduleResponsesNotice:
    def __init__(self, uow: UnitOfWork, queue: JobQueue) -> None:
        self._uow, self._queue = uow, queue

    async def __call__(self, cmd: ScheduleResponsesNoticeCommand) -> None:
        async with self._uow:
            await self._queue.enqueue(
                NOTIFY_RESPONSES,
                ResponsesWindow(job_id=cmd.job_id, since=cmd.at),
                dedup_key=str(cmd.job_id),
                not_before=cmd.at + RESPONSES_DEBOUNCE,
            )
