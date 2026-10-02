"""Лента заявок (GET /jobs, S13; DEVELOPMENT_PLAN 5.3): страница карточек с превью фото —
одним запросом к media на страницу."""

from dataclasses import dataclass

from app.modules.jobs.application.feed import FeedFilters, JobCard
from app.modules.jobs.application.photos import THUMB, photos_of
from app.modules.jobs.application.ports import JobQueries
from app.modules.media.api import MediaApi
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId
from app.platform.kernel.pagination import Page, PageRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class BrowseJobsCommand:
    filters: FeedFilters
    viewer_id: UserId | None
    page: PageRequest


class BrowseJobs:
    def __init__(self, queries: JobQueries, media: MediaApi, clock: Clock) -> None:
        self._queries, self._media, self._clock = queries, media, clock

    async def __call__(self, query: BrowseJobsCommand) -> Page[JobCard]:
        page = await self._queries.feed(
            query.filters, viewer_id=query.viewer_id, page=query.page, now=self._clock.now()
        )
        wanted = {media_id for item in page.items for media_id in item.media_ids}
        refs = await self._media.refs(wanted) if wanted else {}
        return Page(
            items=tuple(
                JobCard(item=item, photos=photos_of(item.media_ids, refs, THUMB))
                for item in page.items
            ),
            next_cursor=page.next_cursor,
        )
