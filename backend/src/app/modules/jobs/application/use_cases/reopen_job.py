"""Сделку по отклику отменили (подписчик DealCancelled; DEVELOPMENT_PLAN 6.1a, ARCHITECTURE
§7.9): заявка снова открыта, прежние кандидаты ждут решения. Уже не «в работе» по этому
отклику (повтор задачи, заявку удалили) — ничего."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobRepository
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.response import ResponseId
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class ReopenJobCommand:
    job_id: JobId
    response_id: ResponseId
    by_performer: bool
    """Отменил исполнитель: его отклик — «отозван», иначе — «отклонён»."""


class ReopenJob:
    def __init__(self, uow: UnitOfWork, jobs: JobRepository, clock: Clock) -> None:
        self._uow, self._jobs, self._clock = uow, jobs, clock

    async def __call__(self, cmd: ReopenJobCommand) -> bool:
        async with self._uow:
            job = await self._jobs.get_for_update(cmd.job_id)
            reopened = job.reopen_after_deal(
                cmd.response_id, by_performer=cmd.by_performer, now=self._clock.now()
            )
            if reopened:
                await self._jobs.save(job)
        return reopened
