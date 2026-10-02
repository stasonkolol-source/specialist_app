"""Отклонить отклик (POST /responses/{id}/decline, S24; DEVELOPMENT_PLAN 6.1a): место на заявке
освобождается, исполнитель видит «не выбран» (ResponseDeclined — уведомление в 6.1b)."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobQueries, JobRepository
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.response import ResponseId
from app.modules.jobs.errors import ResponseNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class DeclineResponseCommand:
    actor_id: UserId
    response_id: ResponseId


class DeclineResponse:
    def __init__(
        self, uow: UnitOfWork, jobs: JobRepository, queries: JobQueries, clock: Clock
    ) -> None:
        self._uow, self._jobs, self._queries, self._clock = uow, jobs, queries, clock

    async def __call__(self, cmd: DeclineResponseCommand) -> JobId:
        job_id = await self._queries.job_of_response(cmd.response_id)
        if job_id is None:
            raise ResponseNotFoundError(response_id=cmd.response_id)
        async with self._uow:
            job = await self._jobs.get_for_update(job_id)
            job.decline_response(cmd.response_id, client_id=cmd.actor_id, now=self._clock.now())
            await self._jobs.save(job)
        return job_id
