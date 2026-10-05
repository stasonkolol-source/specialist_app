"""«Не подходит» (S15, DEVELOPMENT_PLAN 5.3): строка на пару «исполнитель — заявка»."""

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.domain.job import JobId
from app.modules.jobs.infrastructure.models import HiddenJobRow
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


class SqlJobHides:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def hide(self, user_id: UserId, job_id: JobId) -> None:
        self._uow.require_active()
        await self._session.execute(
            insert(HiddenJobRow)
            .values(user_id=user_id, job_id=job_id)
            .on_conflict_do_nothing(index_elements=["user_id", "job_id"])
        )

    async def forget(self, user_id: UserId) -> None:
        self._uow.require_active()
        await self._session.execute(delete(HiddenJobRow).where(HiddenJobRow.user_id == user_id))
