"""Продлить заявку (POST /jobs/{id}/extend, кнопка [Продлить] бота): опубликованную — новый срок
от сейчас, истёкшую — переопубликовать; не больше трёх раз (§7.9, иначе 409)."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobRepository
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.policies import ensure_owner
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ExtendJobCommand:
    actor_id: UserId
    job_id: JobId


class ExtendJob:
    def __init__(self, uow: UnitOfWork, jobs: JobRepository, clock: Clock) -> None:
        self._uow, self._jobs, self._clock = uow, jobs, clock

    async def __call__(self, cmd: ExtendJobCommand) -> None:
        async with self._uow:
            job = await self._jobs.get_for_update(cmd.job_id)
            ensure_owner(job, cmd.actor_id)
            job.extend(now=self._clock.now())
            await self._jobs.save(job)
