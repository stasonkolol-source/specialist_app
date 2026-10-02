"""Журнал запросов без результатов в PostgreSQL (ARCHITECTURE §9.2): пополнение словаря и
еженедельный отчёт (4.3b)."""

from datetime import datetime

from sqlalchemy import Integer, cast, distinct, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.search.application.dto import ZeroResult, ZeroResultStat
from app.modules.search.infrastructure.models import QueryLogRow
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery

_Q = QueryLogRow.__table__.c


class SqlQueryLog(SqlQuery):
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        super().__init__(session)
        self._uow = uow

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

    async def zero_results(self, since: datetime, *, limit: int) -> list[ZeroResultStat]:
        count = func.count().label("count")
        last_seen = func.max(_Q.created_at).label("last_seen")
        rows = await self._fetch(
            select(
                func.mode().within_group(_Q.q).label("q"),
                count,
                func.array_agg(distinct(_Q.locale)).label("locales"),
                func.max(_Q.did_you_mean).label("did_you_mean"),
                func.sum(cast(func.cardinality(_Q.filters) > 0, Integer)).label("narrowed"),
                last_seen,
            )
            .where(_Q.created_at >= since)
            .group_by(_Q.q_norm)
            .order_by(count.desc(), last_seen.desc())
            .limit(limit)
        )
        return [
            ZeroResultStat(
                q=row["q"],
                count=row["count"],
                locales=tuple(sorted(row["locales"])),
                did_you_mean=row["did_you_mean"],
                narrowed=int(row["narrowed"] or 0),
                last_seen=row["last_seen"],
            )
            for row in rows
        ]
