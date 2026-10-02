"""«Не интересно» (POST /jobs/{id}/hide, S15; DEVELOPMENT_PLAN 5.3): опубликованная заявка
пропадает из ленты этого исполнителя. Повтор — без ошибки; невидимая заявка — 404."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobHides, JobQueries
from app.modules.jobs.application.visibility import visible_to
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.errors import JobNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class HideJobCommand:
    actor_id: UserId
    job_id: JobId


class HideJob:
    def __init__(self, uow: UnitOfWork, queries: JobQueries, hides: JobHides) -> None:
        self._uow, self._queries, self._hides = uow, queries, hides

    async def __call__(self, cmd: HideJobCommand) -> None:
        job = await self._queries.view(cmd.job_id)
        if job is None or not await visible_to(self._queries, job, cmd.actor_id):
            raise JobNotFoundError(job_id=cmd.job_id)
        async with self._uow:
            await self._hides.hide(cmd.actor_id, cmd.job_id)
