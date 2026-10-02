"""Избранное в PostgreSQL (ARCHITECTURE §7.3 `search.favorites`)."""

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.search.domain.favorites import FavoriteType
from app.modules.search.infrastructure.models import FavoriteRow
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import UserId

_F = FavoriteRow.__table__.c


class SqlFavorites(SqlQuery):
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        super().__init__(session)
        self._uow = uow

    async def add(self, user_id: UserId, target_type: FavoriteType, target_id: UUID) -> bool:
        self._uow.require_active()
        added = await self._session.execute(
            insert(FavoriteRow)
            .values(user_id=user_id, target_type=target_type, target_id=target_id)
            .on_conflict_do_nothing()
            .returning(_F.target_id)
        )
        return added.first() is not None

    async def remove(self, user_id: UserId, target_type: FavoriteType, target_id: UUID) -> None:
        self._uow.require_active()
        await self._session.execute(
            delete(FavoriteRow).where(
                _F.user_id == user_id, _F.target_type == target_type, _F.target_id == target_id
            )
        )

    async def count(self, user_id: UserId, target_type: FavoriteType) -> int:
        row = await self._fetch_one(
            select(func.count().label("count")).where(
                _F.user_id == user_id, _F.target_type == target_type
            )
        )
        return int(row["count"]) if row is not None else 0

    async def ids(self, user_id: UserId, target_type: FavoriteType) -> list[UUID]:
        rows = await self._fetch(
            select(_F.target_id)
            .where(_F.user_id == user_id, _F.target_type == target_type)
            .order_by(_F.created_at.desc(), _F.target_id.desc())
        )
        return [row["target_id"] for row in rows]

    async def forget(self, user_id: UserId) -> None:
        self._uow.require_active()
        await self._session.execute(delete(FavoriteRow).where(_F.user_id == user_id))
