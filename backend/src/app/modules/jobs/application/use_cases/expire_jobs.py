"""Срок заявок вышел (periodic `jobs.expire_jobs` раз в 5 минут; ARCHITECTURE §7.9, §12).

Опубликованные со сроком в прошлом — «истекла»; клиенту — `job.expired` с «Продлить» и
«Закрыть» (подписчик notifications на JobExpired). Каждая заявка — своей короткой
транзакцией: правка клиента ждёт одну строку, а не весь проход. За проход — не больше
`limit`, остальные — в следующий.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.jobs.application.ports import JobQueries, JobRepository
from app.modules.jobs.errors import JobNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

BATCH: Final = 500


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpireJobsCommand:
    limit: int = BATCH


class ExpireJobs:
    def __init__(
        self, uow: UnitOfWork, jobs: JobRepository, queries: JobQueries, clock: Clock
    ) -> None:
        self._uow, self._jobs, self._queries, self._clock = uow, jobs, queries, clock

    async def __call__(self, cmd: ExpireJobsCommand) -> int:
        """Сколько заявок истекло за проход."""
        now = self._clock.now()
        expired = 0
        for job_id in await self._queries.due_to_expire(now, limit=cmd.limit):
            async with self._uow:
                try:
                    job = await self._jobs.get_for_update(job_id)
                except JobNotFoundError:
                    continue  # удалили между выборкой и блокировкой
                if job.expire(now=now):  # продлённая за это время — уже не истекает
                    await self._jobs.save(job)
                    expired += 1
        return expired
