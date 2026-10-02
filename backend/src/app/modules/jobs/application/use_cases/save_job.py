"""Сохранить заявку (сердечко S15; DEVELOPMENT_PLAN 5.3): опубликованную и видимую исполнителю.
Повтор — без ошибки; невидимая заявка — 404; больше 100 сохранённых — `saved_jobs_full`."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobQueries, SavedJobs
from app.modules.jobs.application.visibility import visible_to
from app.modules.jobs.domain.job import JobId, JobStatus
from app.modules.jobs.domain.policies import MAX_SAVED_JOBS
from app.modules.jobs.errors import JobNotFoundError, SavedJobsFullError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class SaveJobCommand:
    actor_id: UserId
    job_id: JobId


class SaveJob:
    def __init__(self, uow: UnitOfWork, queries: JobQueries, saved: SavedJobs) -> None:
        self._uow, self._queries, self._saved = uow, queries, saved

    async def __call__(self, cmd: SaveJobCommand) -> None:
        job = await self._queries.view(cmd.job_id)
        if (
            job is None
            or job.status is not JobStatus.PUBLISHED
            or not await visible_to(self._queries, job, cmd.actor_id)
        ):
            raise JobNotFoundError(job_id=cmd.job_id)
        async with self._uow:
            if await self._saved.count(cmd.actor_id) >= MAX_SAVED_JOBS:
                if await self._saved.has(cmd.actor_id, cmd.job_id):
                    return
                raise SavedJobsFullError(limit=MAX_SAVED_JOBS)
            await self._saved.save(cmd.actor_id, cmd.job_id)
