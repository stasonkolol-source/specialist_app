"""Закрыть заявку (POST /jobs/{id}/close, кнопка [Закрыть] бота): владелец, с причиной."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobRepository
from app.modules.jobs.domain.job import CloseReason, JobId
from app.modules.jobs.domain.policies import ensure_owner
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class CloseJobCommand:
    actor_id: UserId
    job_id: JobId
    reason: CloseReason


class CloseJob:
    def __init__(self, uow: UnitOfWork, jobs: JobRepository, clock: Clock) -> None:
        self._uow, self._jobs, self._clock = uow, jobs, clock

    async def __call__(self, cmd: CloseJobCommand) -> None:
        async with self._uow:
            job = await self._jobs.get_for_update(cmd.job_id)
            ensure_owner(job, cmd.actor_id)
            job.close(cmd.reason, now=self._clock.now())
            await self._jobs.save(job)
