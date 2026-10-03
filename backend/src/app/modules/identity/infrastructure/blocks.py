"""Блокировки между пользователями (4.7): `identity.user_blocks` — простая запись и чтения
для фасада (фильтры выдачи, ленты, приглашений и переписки) и списка S44."""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import delete, func, or_, select, union_all
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.api import BlockedUser, BlockSide
from app.modules.identity.domain.user import UserStatus
from app.modules.identity.infrastructure.models import UserBlockRow, UserRow
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import UserId

_B = UserBlockRow.__table__.c
_U = UserRow.__table__.c


class SqlBlocks(SqlQuery):
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        super().__init__(session)
        self._uow = uow

    async def add(self, blocker_id: UserId, blocked_id: UserId, *, now: datetime) -> bool:
        self._uow.require_active()
        stmt = (
            insert(UserBlockRow)
            .values(blocker_id=blocker_id, blocked_id=blocked_id, created_at=now)
            .on_conflict_do_nothing(index_elements=["blocker_id", "blocked_id"])
            .returning(_B.blocked_id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def remove(self, blocker_id: UserId, blocked_id: UserId) -> bool:
        self._uow.require_active()
        stmt = (
            delete(UserBlockRow)
            .where(_B.blocker_id == blocker_id, _B.blocked_id == blocked_id)
            .returning(_B.blocked_id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def count(self, blocker_id: UserId) -> int:
        row = await self._fetch_one(
            select(func.count().label("count")).where(_B.blocker_id == blocker_id)
        )
        return int(row["count"]) if row is not None else 0

    async def forget_user(self, user_id: UserId) -> int:
        self._uow.require_active()
        result = await self._session.execute(
            delete(UserBlockRow)
            .where(or_(_B.blocker_id == user_id, _B.blocked_id == user_id))
            .returning(_B.blocked_id)
        )
        return len(result.all())

    async def related(self, user_id: UserId) -> frozenset[UserId]:
        # два индексных прохода — по ключу и по обратному индексу — вместо OR по таблице
        stmt = union_all(
            select(_B.blocked_id.label("other")).where(_B.blocker_id == user_id),
            select(_B.blocker_id.label("other")).where(_B.blocked_id == user_id),
        )
        return frozenset(UserId(row["other"]) for row in await self._fetch(stmt))

    async def sides(self, user_id: UserId, others: Collection[UserId]) -> dict[UserId, BlockSide]:
        if not others:
            return {}
        wanted = list(others)
        rows = await self._fetch(
            select(_B.blocker_id, _B.blocked_id).where(
                or_(
                    (_B.blocker_id == user_id) & _B.blocked_id.in_(wanted),
                    (_B.blocked_id == user_id) & _B.blocker_id.in_(wanted),
                )
            )
        )
        found: dict[UserId, BlockSide] = {}
        for row in rows:
            if row["blocker_id"] == user_id:
                found[UserId(row["blocked_id"])] = BlockSide.BY_ME  # своя — главнее: её снимают
            else:
                found.setdefault(UserId(row["blocker_id"]), BlockSide.BY_THEM)
        return found

    async def blocked_users(self, user_id: UserId) -> list[BlockedUser]:
        rows = await self._fetch(
            select(_B.blocked_id, _B.created_at, _U.display_name)
            .join(UserRow.__table__, _U.id == _B.blocked_id)
            .where(_B.blocker_id == user_id, _U.status == UserStatus.ACTIVE)
            .order_by(_B.created_at.desc(), _B.blocked_id.desc())
        )
        return [
            BlockedUser(
                user_id=UserId(row["blocked_id"]),
                display_name=row["display_name"],
                blocked_at=row["created_at"],
            )
            for row in rows
        ]
