"""Двое заблокировали друг друга (подписчик UserBlocked; DEVELOPMENT_PLAN 4.7, MU-3): отклики
одного на заявки другого перестают занимать места.

Блокировка прячет отклик от клиента в обе стороны, и решить по нему он уже не может: место
пропадало, а «N из 5» расходилось со списком откликов. Отклик заблокированного исполнителя —
«не выбран», как у любого не выбранного: о блокировке ему не сообщаем. Отклик исполнителя,
который сам заблокировал клиента, — «отозван». Каждая заявка — своей транзакцией под
блокировкой её строки; повтор задачи ничего не меняет.
"""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobQueries, JobRepository
from app.modules.jobs.errors import JobNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ReleaseBlockedResponsesCommand:
    blocker_id: UserId
    blocked_id: UserId


class ReleaseBlockedResponses:
    def __init__(
        self, uow: UnitOfWork, jobs: JobRepository, queries: JobQueries, clock: Clock
    ) -> None:
        self._uow, self._jobs, self._queries, self._clock = uow, jobs, queries, clock

    async def __call__(self, cmd: ReleaseBlockedResponsesCommand) -> int:
        """Сколько откликов освободило места."""
        released = 0
        # (чей отклик, на чьи заявки, отозван ли он самим исполнителем)
        sides = (
            (cmd.blocked_id, cmd.blocker_id, False),
            (cmd.blocker_id, cmd.blocked_id, True),
        )
        for performer_id, client_id, withdrawn in sides:
            for job_id in await self._queries.performer_jobs(performer_id):
                async with self._uow:
                    try:
                        job = await self._jobs.get_for_update(job_id)
                    except JobNotFoundError:
                        continue
                    if job.client_id != client_id:
                        continue
                    if job.release_blocked_response(
                        performer_id, withdrawn=withdrawn, now=self._clock.now()
                    ):
                        await self._jobs.save(job)
                        released += 1
        return released
