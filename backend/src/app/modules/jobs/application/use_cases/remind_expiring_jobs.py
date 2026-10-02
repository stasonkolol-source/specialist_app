"""Напомнить о конце срока (periodic `jobs.expiry_reminders` раз в 15 минут; §11.3, §12).

Опубликованным, у которых до конца срока не больше двух часов, — JobExpiring: клиенту
«Заявка закроется через 2 ч» с «Продлить» и «Закрыть: исполнитель найден» (подписчик
notifications). Одно напоминание за срок: продление и новая публикация его сбрасывают.
Каждая заявка — своей короткой транзакцией, за проход — не больше `limit`.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.jobs.application.ports import JobQueries, JobRepository
from app.modules.jobs.domain.job import REMINDER_LEAD
from app.modules.jobs.errors import JobNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

BATCH: Final = 500


@dataclass(frozen=True, slots=True, kw_only=True)
class RemindExpiringJobsCommand:
    limit: int = BATCH


class RemindExpiringJobs:
    def __init__(
        self, uow: UnitOfWork, jobs: JobRepository, queries: JobQueries, clock: Clock
    ) -> None:
        self._uow, self._jobs, self._queries, self._clock = uow, jobs, queries, clock

    async def __call__(self, cmd: RemindExpiringJobsCommand) -> int:
        """Скольким заявкам напомнили за проход."""
        now = self._clock.now()
        reminded = 0
        for job_id in await self._queries.expiring(now, now + REMINDER_LEAD, limit=cmd.limit):
            async with self._uow:
                try:
                    job = await self._jobs.get_for_update(job_id)
                except JobNotFoundError:
                    continue
                if job.remind_expiry(now=now):
                    await self._jobs.save(job)
                    reminded += 1
        return reminded
