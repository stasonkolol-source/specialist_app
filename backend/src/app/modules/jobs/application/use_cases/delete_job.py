"""Удалить заявку (DELETE /jobs/{id}, soft): пропадает из списков и ленты сразу, открытая ещё и
закрывается; физически удаляет ретеншн (§7.10)."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobRepository
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.policies import ensure_owner
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class DeleteJobCommand:
    actor_id: UserId
    job_id: JobId


class DeleteJob:
    def __init__(self, uow: UnitOfWork, jobs: JobRepository, clock: Clock) -> None:
        self._uow, self._jobs, self._clock = uow, jobs, clock

    async def __call__(self, cmd: DeleteJobCommand) -> None:
        async with self._uow:
            job = await self._jobs.get_for_update(cmd.job_id)
            ensure_owner(job, cmd.actor_id)
            job.delete(now=self._clock.now())
            await self._jobs.save(job)
