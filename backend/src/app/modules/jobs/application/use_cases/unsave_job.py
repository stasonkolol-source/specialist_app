"""Убрать заявку из сохранённых (сердечко S15; DEVELOPMENT_PLAN 5.3): чего нет — без ошибки,
статус заявки не важен."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import SavedJobs
from app.modules.jobs.domain.job import JobId
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class UnsaveJobCommand:
    actor_id: UserId
    job_id: JobId


class UnsaveJob:
    def __init__(self, uow: UnitOfWork, saved: SavedJobs) -> None:
        self._uow, self._saved = uow, saved

    async def __call__(self, cmd: UnsaveJobCommand) -> None:
        async with self._uow:
            await self._saved.unsave(cmd.actor_id, cmd.job_id)
