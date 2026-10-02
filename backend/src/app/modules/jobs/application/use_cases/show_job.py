"""Карточка заявки (GET /jobs/{id}; S15 исполнителю и гостю, S23 владельцу): заявка, её фото,
блок клиента «в «Соседях» N месяцев · M заявок» (пробел §8.5) и свой отклик исполнителя —
«Вы откликнулись» (5.5). Что из заявки показать — решает HTTP по политике (точка и адрес —
только владельцу)."""

from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.api import IdentityApi
from app.modules.jobs.application.dto import JobView, MyResponseRef
from app.modules.jobs.application.feed import Photo
from app.modules.jobs.application.photos import LARGE, photos_of
from app.modules.jobs.application.ports import JobQueries
from app.modules.jobs.application.visibility import visible_to
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.errors import JobNotFoundError
from app.modules.media.api import MediaApi
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class JobClient:
    display_name: str
    member_since: datetime
    jobs_count: int
    """Сколько заявок клиента публиковалось."""
    phone_verified: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class JobDetails:
    job: JobView
    photos: tuple[Photo, ...]
    client: JobClient | None
    """None — аккаунт клиента удалён."""
    my_response: MyResponseRef | None = None
    """Отклик зрителя-исполнителя; гостю и владельцу — None."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ShowJobCommand:
    job_id: JobId
    viewer_id: UserId | None


class ShowJob:
    def __init__(self, queries: JobQueries, media: MediaApi, identity: IdentityApi) -> None:
        self._queries, self._media, self._identity = queries, media, identity

    async def __call__(self, query: ShowJobCommand) -> JobDetails:
        job = await self._queries.view(query.job_id)
        if job is None or not await visible_to(self._queries, job, query.viewer_id):
            raise JobNotFoundError(job_id=query.job_id)
        refs = await self._media.refs(job.media_ids) if job.media_ids else {}
        user = await self._identity.get_user(job.client_id)
        client = None
        if user is not None and not user.is_deleted:
            client = JobClient(
                display_name=user.display_name,
                member_since=user.created_at,
                jobs_count=await self._queries.count_published(job.client_id),
                phone_verified=user.phone_verified,
            )
        mine = None
        if query.viewer_id is not None and query.viewer_id != job.client_id:
            mine = await self._queries.performer_response(query.job_id, query.viewer_id)
        return JobDetails(
            job=job,
            photos=photos_of(job.media_ids, refs, LARGE),
            client=client,
            my_response=mine,
        )
