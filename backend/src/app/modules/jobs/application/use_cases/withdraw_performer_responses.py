"""Отклики удалённого аккаунта (UserDeleted, ARCHITECTURE §7.10): активные отзываются — места на
чужих заявках освобождаются, клиенты больше их не видят. Каждая заявка — своей транзакцией под
блокировкой её строки: долгой общей блокировки нет."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobQueries, JobRepository
from app.modules.jobs.errors import JobNotFoundError, ResponseNotActiveError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class WithdrawPerformerResponsesCommand:
    user_id: UserId


class WithdrawPerformerResponses:
    def __init__(
        self, uow: UnitOfWork, jobs: JobRepository, queries: JobQueries, clock: Clock
    ) -> None:
        self._uow, self._jobs, self._queries, self._clock = uow, jobs, queries, clock

    async def __call__(self, cmd: WithdrawPerformerResponsesCommand) -> int:
        withdrawn = 0
        for job_id in await self._queries.performer_jobs(cmd.user_id):
            async with self._uow:
                try:
                    job = await self._jobs.get_for_update(job_id)
                except JobNotFoundError:
                    continue
                for response in [r for r in job.responses if r.performer_id == cmd.user_id]:
                    try:
                        job.withdraw_response(
                            response.id, performer_id=cmd.user_id, now=self._clock.now()
                        )
                    except ResponseNotActiveError:
                        continue
                    withdrawn += 1
                await self._jobs.save(job)
        return withdrawn
