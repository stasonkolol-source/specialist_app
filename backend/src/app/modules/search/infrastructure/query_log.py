"""Журнал запросов без результатов в PostgreSQL (ARCHITECTURE §9.2): пополнение словаря."""

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.search.application.dto import ZeroResult
from app.modules.search.infrastructure.models import QueryLogRow
from app.platform.db.port import UnitOfWork


class SqlQueryLog:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def record(self, entry: ZeroResult) -> None:
        self._uow.require_active()
        await self._session.execute(
            insert(QueryLogRow).values(
                q=entry.q,
                locale=entry.locale,
                city_id=entry.city_id,
                category_id=entry.category_id,
                filters=list(entry.filters),
                did_you_mean=entry.did_you_mean,
            )
        )
