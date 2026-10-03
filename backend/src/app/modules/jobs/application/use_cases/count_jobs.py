"""Сколько заявок в ленте с фильтрами (GET /jobs/count; DEVELOPMENT_PLAN 5.3): «Показать N»
шторки S14 и «N новых задач рядом» Главной. Считается то же, что показывает лента: без своих,
скрытых и заявок тех, с кем у зрителя блокировка (4.7)."""

from dataclasses import dataclass, replace
from datetime import timedelta

from app.modules.identity.api import IdentityApi
from app.modules.jobs.application.blocks import without_blocked
from app.modules.jobs.application.feed import FeedFilters
from app.modules.jobs.application.ports import JobQueries
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class CountJobsCommand:
    filters: FeedFilters
    viewer_id: UserId | None
    new_hours: int | None = None
    """Только опубликованные за последние часы — «новые» на Главной."""


class CountJobs:
    def __init__(self, queries: JobQueries, identity: IdentityApi, clock: Clock) -> None:
        self._queries, self._identity, self._clock = queries, identity, clock

    async def __call__(self, query: CountJobsCommand) -> int:
        now = self._clock.now()
        filters = query.filters
        if query.new_hours is not None:
            filters = replace(filters, published_after=now - timedelta(hours=query.new_hours))
        filters = await without_blocked(self._identity, filters, query.viewer_id)
        return await self._queries.feed_count(filters, viewer_id=query.viewer_id, now=now)
