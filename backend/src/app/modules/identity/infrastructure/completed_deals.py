"""Факты завершённых сделок (6.1a): `identity.completed_deals`, одна строка на сторону сделки."""

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.infrastructure.models import CompletedDealRow
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import DealId, UserId


class SqlCompletedDeals:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def record(self, user_id: UserId, deal_id: DealId, at: datetime) -> bool:
        self._uow.require_active()
        stmt = (
            insert(CompletedDealRow)
            .values(user_id=user_id, deal_id=deal_id, completed_at=at)
            .on_conflict_do_nothing(index_elements=["user_id", "deal_id"])
            .returning(CompletedDealRow.user_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None
