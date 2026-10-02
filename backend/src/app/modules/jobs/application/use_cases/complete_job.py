"""Сделка по отклику завершена (подписчик DealCompleted; DEVELOPMENT_PLAN 6.1a): заявка
«завершена». Уже не «в работе» по этому отклику — ничего."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobRepository
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.response import ResponseId
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class CompleteJobCommand:
    job_id: JobId
    response_id: ResponseId


class CompleteJob:
    def __init__(self, uow: UnitOfWork, jobs: JobRepository, clock: Clock) -> None:
        self._uow, self._jobs, self._clock = uow, jobs, clock

    async def __call__(self, cmd: CompleteJobCommand) -> bool:
        async with self._uow:
            job = await self._jobs.get_for_update(cmd.job_id)
            completed = job.complete_after_deal(cmd.response_id, now=self._clock.now())
            if completed:
                await self._jobs.save(job)
        return completed
