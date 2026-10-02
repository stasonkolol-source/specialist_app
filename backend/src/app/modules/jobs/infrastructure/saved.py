"""Сохранённые заявки (сердечко S15, S12; DEVELOPMENT_PLAN 5.3): строка на пару «исполнитель —
заявка»."""

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.domain.job import JobId
from app.modules.jobs.infrastructure.models import SavedJobRow
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import UserId

_S = SavedJobRow.__table__.c


class SqlSavedJobs(SqlQuery):
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        super().__init__(session)
        self._uow = uow

    async def save(self, user_id: UserId, job_id: JobId) -> None:
        self._uow.require_active()
        await self._session.execute(
            insert(SavedJobRow)
            .values(user_id=user_id, job_id=job_id)
            .on_conflict_do_nothing(index_elements=["user_id", "job_id"])
        )

    async def unsave(self, user_id: UserId, job_id: JobId) -> None:
        self._uow.require_active()
        await self._session.execute(
            delete(SavedJobRow).where(_S.user_id == user_id, _S.job_id == job_id)
        )

    async def count(self, user_id: UserId) -> int:
        row = await self._fetch_one(
            select(func.count().label("count")).where(_S.user_id == user_id)
        )
        return int(row["count"]) if row is not None else 0

    async def has(self, user_id: UserId, job_id: JobId) -> bool:
        row = await self._fetch_one(
            select(_S.job_id).where(_S.user_id == user_id, _S.job_id == job_id)
        )
        return row is not None

    async def forget(self, user_id: UserId) -> None:
        self._uow.require_active()
        await self._session.execute(delete(SavedJobRow).where(_S.user_id == user_id))
