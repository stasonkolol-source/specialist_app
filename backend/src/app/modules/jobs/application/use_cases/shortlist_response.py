"""«В избранные» (POST /responses/{id}/shortlist, S24; DEVELOPMENT_PLAN 6.1a): клиент отмечает
лучших кандидатов; повтор — без изменений."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobQueries, JobRepository
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.response import ResponseId
from app.modules.jobs.errors import ResponseNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ShortlistResponseCommand:
    actor_id: UserId
    response_id: ResponseId


class ShortlistResponse:
    def __init__(
        self, uow: UnitOfWork, jobs: JobRepository, queries: JobQueries, clock: Clock
    ) -> None:
        self._uow, self._jobs, self._queries, self._clock = uow, jobs, queries, clock

    async def __call__(self, cmd: ShortlistResponseCommand) -> JobId:
        job_id = await self._queries.job_of_response(cmd.response_id)
        if job_id is None:
            raise ResponseNotFoundError(response_id=cmd.response_id)
        async with self._uow:
            job = await self._jobs.get_for_update(job_id)
            job.shortlist_response(cmd.response_id, client_id=cmd.actor_id, now=self._clock.now())
            await self._jobs.save(job)
        return job_id
