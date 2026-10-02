"""Просмотр заявки (GET /jobs/{id} не владельцем; S23 «просмотры», DEVELOPMENT_PLAN 5.6): от одного
человека — не чаще раза в сутки. Гость не считается: его не отличить от повторного открытия."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobViews
from app.modules.jobs.domain.job import JobId
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class CountJobViewCommand:
    job_id: JobId
    viewer_id: UserId


class CountJobView:
    def __init__(self, uow: UnitOfWork, views: JobViews) -> None:
        self._uow, self._views = uow, views

    async def __call__(self, cmd: CountJobViewCommand) -> None:
        async with self._uow:
            await self._views.count(cmd.job_id, cmd.viewer_id)
