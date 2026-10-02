"""Очередь пересборки read-model в PostgreSQL: таблица отметок вместо задачи на событие.

Несколько событий одного профиля дают одну пересборку, а задача берёт пачку — так 1 000
событий проходят за секунды (DEVELOPMENT_PLAN 4.1, лаг p95 < 10 с).
"""

from collections.abc import Collection
from datetime import datetime
from itertools import batched
from typing import Final
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.search.application.ports import Pending
from app.modules.search.infrastructure.models import PendingProfileRow
from app.platform.db.port import UnitOfWork

CHUNK: Final = 1000
"""Отметок за INSERT: у PostgreSQL предел 65 535 параметров, а категория верхнего уровня
(CatalogChanged) на масштабе лаборатории отмечает десятки тысяч профилей."""


class SqlPendingProfiles:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def mark(self, profile_ids: Collection[UUID], *, occurred_at: datetime | None) -> int:
        self._uow.require_active()
        ids = list(dict.fromkeys(profile_ids))
        if not ids:
            return 0
        for chunk in batched(ids, CHUNK, strict=False):
            rows = [{"profile_id": profile_id, "occurred_at": occurred_at} for profile_id in chunk]
            stmt = insert(PendingProfileRow).values(rows)
            earliest = func.least(PendingProfileRow.occurred_at, stmt.excluded.occurred_at)
            await self._session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["profile_id"], set_={"occurred_at": earliest}
                )
            )
        return len(ids)

    async def take(self, *, limit: int) -> list[Pending]:
        self._uow.require_active()
        stmt = (
            select(PendingProfileRow.profile_id, PendingProfileRow.occurred_at)
            .order_by(PendingProfileRow.marked_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.execute(stmt)).all()
        return [Pending(profile_id=row[0], occurred_at=row[1]) for row in rows]

    async def clear(self, profile_ids: Collection[UUID]) -> None:
        self._uow.require_active()
        ids = list(profile_ids)
        if ids:
            column = PendingProfileRow.profile_id
            await self._session.execute(delete(PendingProfileRow).where(column.in_(ids)))

    async def count(self) -> int:
        stmt = select(func.count()).select_from(PendingProfileRow)
        return int((await self._session.execute(stmt)).scalar_one())
