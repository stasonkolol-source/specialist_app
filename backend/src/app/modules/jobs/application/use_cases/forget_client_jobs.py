"""Заявки удалённого аккаунта (UserDeleted, ARCHITECTURE §7.10): открытые закрываются, все —
удаляются из выдачи, точная точка и адрес стираются сразу — и у удалённых раньше; скрытые им в
ленте и сохранённые заявки, шаблоны откликов забываются."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import (
    JobHides,
    JobRepository,
    ResponseTemplates,
    SavedJobs,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetClientJobsCommand:
    user_id: UserId


class ForgetClientJobs:
    def __init__(
        self,
        uow: UnitOfWork,
        jobs: JobRepository,
        hides: JobHides,
        saved: SavedJobs,
        templates: ResponseTemplates,
        clock: Clock,
    ) -> None:
        self._uow, self._jobs, self._hides, self._saved = uow, jobs, hides, saved
        self._templates, self._clock = templates, clock

    async def __call__(self, cmd: ForgetClientJobsCommand) -> int:
        now = self._clock.now()
        async with self._uow:
            ids = await self._jobs.of_client(cmd.user_id)
            for job_id in ids:
                job = await self._jobs.get_for_update(job_id)
                job.delete(now=now, by_system=True)
                await self._jobs.save(job)
            await self._jobs.forget_private(cmd.user_id)
            await self._hides.forget(cmd.user_id)
            await self._saved.forget(cmd.user_id)
            await self._templates.forget(cmd.user_id)
        return len(ids)
