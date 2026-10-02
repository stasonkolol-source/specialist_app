"""HTTP jobs (DEVELOPMENT_PLAN 5.1; ARCHITECTURE §8.5): заявка клиента от создания до закрытия.

- `POST /jobs` (Idempotency-Key) — сразу на проверку: ответ `pending_moderation` (модерация
  публикует асинхронно) или уже `published`. `POST /jobs/{id}/submit` из §8.5 нет: черновик
  живёт только на клиенте (5.2).
- `GET /jobs/{id}` 🔓 — гость и исполнитель видят опубликованную, без точной точки и адреса;
  владелец — свою в любом статусе (`viewer_role: owner`), с ETag для If-Match.
- `PATCH /jobs/{id}` (If-Match → 412), `POST /jobs/{id}/close`, `POST /jobs/{id}/extend`,
  `DELETE /jobs/{id}` — только владелец; чужая заявка — 404.
- `GET /me/jobs?status=` — свои заявки, новые первыми.
- `GET /jobs` 🔓 — лента исполнителя (S13, 5.3): заявки города, свежие сверху, фильтры §9.6,
  курсор; `GET /jobs/count` 🔓 — «Показать N» шторки S14 и «N новых задач рядом» Главной.
- `POST /jobs/{id}/hide` — «не интересно»: заявка пропадает из ленты этого исполнителя.
- `GET /me/favorites/jobs`, `PUT` и `DELETE /me/favorites/job/{id}` — сохранённые заявки
  (сердечко S15, сегмент «Задачи» S12): открытые, новые первыми, до ста (`saved_jobs_full`).
- Отклики (5.4): `POST /jobs/{id}/responses` (Idempotency-Key) — пять мест на заявку под
  блокировкой её строки, суточный лимит по уровню доверия; `PATCH /responses/{id}`,
  `POST /responses/{id}/withdraw` — исполнителю, пока клиент не решил; `GET /me/responses` —
  «Мои отклики» S17; `GET /jobs/{id}/responses` — владельцу заявки (S23).
Лимиты новичка — в use case (§13.3); лента и счётчик — 60 / 120 запросов в минуту.
"""

from dataclasses import replace
from datetime import timedelta
from typing import Annotated, Final
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.modules.jobs.application.feed import FeedFilters
from app.modules.jobs.application.photos import LARGE, photos_of
from app.modules.jobs.application.ports import JobQueries
from app.modules.jobs.application.responses import ResponseGroup
from app.modules.jobs.application.use_cases.browse_jobs import BrowseJobs, BrowseJobsCommand
from app.modules.jobs.application.use_cases.close_job import CloseJob, CloseJobCommand
from app.modules.jobs.application.use_cases.create_job import CreateJob, CreateJobCommand
from app.modules.jobs.application.use_cases.delete_job import DeleteJob, DeleteJobCommand
from app.modules.jobs.application.use_cases.edit_job import EditJob, EditJobCommand
from app.modules.jobs.application.use_cases.extend_job import ExtendJob, ExtendJobCommand
from app.modules.jobs.application.use_cases.hide_job import HideJob, HideJobCommand
from app.modules.jobs.application.use_cases.list_job_responses import (
    ListJobResponses,
    ListJobResponsesCommand,
)
from app.modules.jobs.application.use_cases.list_my_responses import (
    ListMyResponses,
    ListMyResponsesCommand,
)
from app.modules.jobs.application.use_cases.list_saved_jobs import (
    ListSavedJobs,
    ListSavedJobsCommand,
)
from app.modules.jobs.application.use_cases.respond import Respond, RespondCommand
from app.modules.jobs.application.use_cases.revise_response import (
    ReviseResponse,
    ReviseResponseCommand,
)
from app.modules.jobs.application.use_cases.save_job import SaveJob, SaveJobCommand
from app.modules.jobs.application.use_cases.show_job import JobDetails, ShowJob, ShowJobCommand
from app.modules.jobs.application.use_cases.unsave_job import UnsaveJob, UnsaveJobCommand
from app.modules.jobs.application.use_cases.withdraw_response import (
    WithdrawResponse,
    WithdrawResponseCommand,
)
from app.modules.jobs.domain.job import CloseReason, JobId, JobStatus, Urgency
from app.modules.jobs.domain.response import ResponseId
from app.modules.jobs.errors import JobNotFoundError, ResponseNotFoundError
from app.modules.jobs.http.schemas import (
    JobCardOut,
    JobCloseIn,
    JobIn,
    JobOut,
    JobResponseOut,
    JobResponsesOut,
    JobsCountOut,
    JobsOut,
    JobsPageOut,
    MyResponseOut,
    MyResponsesPageOut,
    ResponseCountsOut,
    ResponseIn,
    SavedJobsOut,
    TodayOut,
)
from app.modules.media.api import MediaApi
from app.platform.http.concurrency import IfMatch, set_etag
from app.platform.http.idempotency import idempotent_router
from app.platform.http.ratelimit import GuestOrUserRateLimit
from app.platform.http.security import AUTHENTICATED, optional_principal
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId
from app.platform.kernel.localized import Locale
from app.platform.kernel.pagination import DEFAULT_LIMIT, PageRequest
from app.platform.kernel.principal import Principal
from app.platform.ratelimit import Rate

MY_JOBS_LIMIT: Final = 50
MY_RESPONSES_LIMIT: Final = 50
FEED_MAX_LIMIT: Final = 50
MAX_RADIUS_KM: Final = 50
MAX_NEW_HOURS: Final = 168
FEED_GUEST = Rate("jobs.feed_guest", "60/minute")
FEED_USER = Rate("jobs.feed_user", "120/minute")
feed_limit = [Depends(GuestOrUserRateLimit(guest=FEED_GUEST, user=FEED_USER))]

router = APIRouter(tags=["jobs"])
creating = idempotent_router()
JobPath = Annotated[UUID, Path(description="id заявки")]
ResponsePath = Annotated[UUID, Path(description="id отклика")]
Viewer = Annotated[Principal | None, Depends(optional_principal)]


@creating.post(
    "/jobs", status_code=status.HTTP_201_CREATED, response_model=JobOut, dependencies=AUTHENTICATED
)
@inject
async def create_job(
    body: JobIn,
    principal: FromDishka[Principal],
    locale: FromDishka[Locale],
    create: FromDishka[CreateJob],
    show: FromDishka[ShowJob],
    response: Response,
) -> JobOut:
    """Создать заявку: сразу на проверку, лимиты новичка — 429."""
    job_id = await create(
        CreateJobCommand(
            actor_id=principal.user_id,
            trust_level=principal.trust_level,
            draft=body.draft(_language(locale)),
        )
    )
    return await _own(show, job_id, principal.user_id, response)


@creating.post(
    "/jobs/{job_id:uuid}/responses",
    status_code=status.HTTP_201_CREATED,
    response_model=MyResponseOut,
    dependencies=AUTHENTICATED,
)
@inject
async def respond(
    job_id: JobPath,
    body: ResponseIn,
    principal: FromDishka[Principal],
    respond: FromDishka[Respond],
    queries: FromDishka[JobQueries],
) -> MyResponseOut:
    """Откликнуться (S16): заявка открыта, не своя и есть место — иначе 409 (`job_not_open`,
    `own_job`, `already_responded`, `job_full`); суточный лимит по уровню доверия — 429. Текст
    уходит на проверку: клиент увидит отклик после неё."""
    _, response_id = await respond(
        RespondCommand(
            actor_id=principal.user_id,
            trust_level=principal.trust_level,
            job_id=JobId(job_id),
            offer=body.offer(),
        )
    )
    return await _my_response(queries, principal.user_id, response_id)


router.include_router(creating)


def feed_filters(
    *,
    city_id: Annotated[int, Query(ge=1, description="Город ленты")],
    category: Annotated[
        list[int] | None, Query(description="Категории: с подкатегориями, любая из них")
    ] = None,
    district: Annotated[list[int] | None, Query(description="Районы: любой из них")] = None,
    lat: Annotated[float | None, Query(ge=-90, le=90, description="Точка зрителя")] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[
        float | None, Query(gt=0, le=MAX_RADIUS_KM, description="Радиус от точки")
    ] = None,
    urgency: Annotated[list[Urgency] | None, Query()] = None,
    budget_from: Annotated[
        int | None, Query(ge=1, description="Пара: бюджет не меньше (договорные — нет)")
    ] = None,
    lang: Annotated[
        list[str] | None, Query(description="Языки общения: заявки на любом из них")
    ] = None,
    has_photos: Annotated[bool, Query(description="Только с фото")] = False,
) -> FeedFilters:
    if (lat is None) != (lon is None):
        raise DomainValidationError(field="lon" if lon is None else "lat", reason="pair")
    if radius_km is not None and lat is None:
        raise DomainValidationError(field="radius_km", reason="needs_point")
    return FeedFilters(
        city_id=CityId(city_id),
        category_ids=tuple(CategoryId(item) for item in dict.fromkeys(category or [])),
        district_ids=tuple(DistrictId(item) for item in dict.fromkeys(district or [])),
        near=GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None,
        radius_m=round(radius_km * 1000) if radius_km is not None else None,
        urgencies=tuple(dict.fromkeys(urgency or [])),
        budget_from=budget_from,
        languages=tuple(dict.fromkeys(lang or [])),
        with_photos=has_photos,
    )


Feed = Annotated[FeedFilters, Depends(feed_filters)]


@router.get("/jobs", response_model=JobsPageOut, dependencies=feed_limit)
@inject
async def list_jobs(
    filters: Feed,
    viewer: Viewer,
    browse: FromDishka[BrowseJobs],
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=FEED_MAX_LIMIT)] = DEFAULT_LIMIT,
) -> JobsPageOut:
    """Лента 🔓 (S13): опубликованные заявки города, свежие сверху; свои и скрытые — нет."""
    page = await browse(
        BrowseJobsCommand(
            filters=filters,
            viewer_id=viewer.user_id if viewer is not None else None,
            page=PageRequest(limit=limit, cursor=cursor),
        )
    )
    return JobsPageOut(
        items=[JobCardOut.of(card) for card in page.items], next_cursor=page.next_cursor
    )


@router.get("/jobs/count", response_model=JobsCountOut, dependencies=feed_limit)
@inject
async def count_jobs(
    filters: Feed,
    viewer: Viewer,
    queries: FromDishka[JobQueries],
    clock: FromDishka[Clock],
    new_hours: Annotated[
        int | None, Query(ge=1, le=MAX_NEW_HOURS, description="Только опубликованные за часы")
    ] = None,
) -> JobsCountOut:
    """Сколько заявок с фильтрами 🔓: «Показать N» S14, «N новых задач рядом» на Главной."""
    now = clock.now()
    if new_hours is not None:
        filters = replace(filters, published_after=now - timedelta(hours=new_hours))
    count = await queries.feed_count(
        filters, viewer_id=viewer.user_id if viewer is not None else None, now=now
    )
    return JobsCountOut(count=count)


@router.get("/jobs/{job_id:uuid}", response_model=JobOut)
@inject
async def get_job(
    job_id: JobPath, viewer: Viewer, show: FromDishka[ShowJob], response: Response
) -> JobOut:
    """Заявка 🔓: опубликованная — всем без точной точки и адреса, своя — владельцу целиком."""
    viewer_id = viewer.user_id if viewer is not None else None
    details = await show(ShowJobCommand(job_id=JobId(job_id), viewer_id=viewer_id))
    owner = viewer_id == details.job.client_id
    if owner:
        set_etag(response, details.job.version)
    return JobOut.of(details, owner=owner)


@router.post(
    "/jobs/{job_id:uuid}/hide",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=AUTHENTICATED,
)
@inject
async def hide_job(
    job_id: JobPath, principal: FromDishka[Principal], hide: FromDishka[HideJob]
) -> None:
    """«Не интересно» (S15): заявка пропадает из ленты; повтор — без ошибки."""
    await hide(HideJobCommand(actor_id=principal.user_id, job_id=JobId(job_id)))


@router.get("/me/favorites/jobs", response_model=SavedJobsOut, dependencies=AUTHENTICATED)
@inject
async def list_saved_jobs(
    principal: FromDishka[Principal], saved: FromDishka[ListSavedJobs]
) -> SavedJobsOut:
    """Сохранённые заявки S12: открытые, новые сохранения первыми; закрытые и истёкшие — не
    в списке."""
    cards = await saved(ListSavedJobsCommand(actor_id=principal.user_id))
    return SavedJobsOut(items=[JobCardOut.of(card) for card in cards])


@router.put(
    "/me/favorites/job/{job_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=AUTHENTICATED,
)
@inject
async def save_job(
    job_id: JobPath, principal: FromDishka[Principal], save: FromDishka[SaveJob]
) -> None:
    """Сердечко S15: заявка — в сохранённые. Повтор — без ошибки; невидимая — 404; больше ста —
    `saved_jobs_full`."""
    await save(SaveJobCommand(actor_id=principal.user_id, job_id=JobId(job_id)))


@router.delete(
    "/me/favorites/job/{job_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=AUTHENTICATED,
)
@inject
async def unsave_job(
    job_id: JobPath, principal: FromDishka[Principal], unsave: FromDishka[UnsaveJob]
) -> None:
    """Убрать заявку из сохранённых; чего нет — без ошибки."""
    await unsave(UnsaveJobCommand(actor_id=principal.user_id, job_id=JobId(job_id)))


@router.patch("/jobs/{job_id:uuid}", response_model=JobOut, dependencies=AUTHENTICATED)
@inject
async def update_job(
    job_id: JobPath,
    body: JobIn,
    expected_version: IfMatch,
    principal: FromDishka[Principal],
    locale: FromDishka[Locale],
    edit: FromDishka[EditJob],
    show: FromDishka[ShowJob],
    response: Response,
) -> JobOut:
    """Правка владельцем целиком: отклонённая и существенно изменённая — снова на проверку."""
    await edit(
        EditJobCommand(
            actor_id=principal.user_id,
            job_id=JobId(job_id),
            draft=body.draft(_language(locale)),
            expected_version=expected_version,
        )
    )
    return await _own(show, JobId(job_id), principal.user_id, response)


@router.post("/jobs/{job_id:uuid}/close", response_model=JobOut, dependencies=AUTHENTICATED)
@inject
async def close_job(
    job_id: JobPath,
    body: JobCloseIn,
    principal: FromDishka[Principal],
    close: FromDishka[CloseJob],
    show: FromDishka[ShowJob],
    response: Response,
) -> JobOut:
    """Закрыть с причиной: нашёл здесь, нашёл в другом месте, уже не нужно, не подошли."""
    await close(
        CloseJobCommand(
            actor_id=principal.user_id, job_id=JobId(job_id), reason=CloseReason(body.reason)
        )
    )
    return await _own(show, JobId(job_id), principal.user_id, response)


@router.post("/jobs/{job_id:uuid}/extend", response_model=JobOut, dependencies=AUTHENTICATED)
@inject
async def extend_job(
    job_id: JobPath,
    principal: FromDishka[Principal],
    extend: FromDishka[ExtendJob],
    show: FromDishka[ShowJob],
    response: Response,
) -> JobOut:
    """Продлить опубликованную или переопубликовать истёкшую; четвёртый раз — 409."""
    await extend(ExtendJobCommand(actor_id=principal.user_id, job_id=JobId(job_id)))
    return await _own(show, JobId(job_id), principal.user_id, response)


@router.delete(
    "/jobs/{job_id:uuid}", status_code=status.HTTP_204_NO_CONTENT, dependencies=AUTHENTICATED
)
@inject
async def delete_job(
    job_id: JobPath, principal: FromDishka[Principal], delete: FromDishka[DeleteJob]
) -> None:
    """Удалить (soft): из списков и ленты — сразу, открытая ещё и закрывается."""
    await delete(DeleteJobCommand(actor_id=principal.user_id, job_id=JobId(job_id)))


@router.get("/me/jobs", response_model=JobsOut, dependencies=AUTHENTICATED)
@inject
async def list_my_jobs(
    principal: FromDishka[Principal],
    queries: FromDishka[JobQueries],
    media: FromDishka[MediaApi],
    statuses: Annotated[
        list[JobStatus] | None, Query(alias="status", description="Без фильтра — все")
    ] = None,
) -> JobsOut:
    """Свои заявки (S22), новые первыми; блока клиента в своём списке нет."""
    jobs = await queries.own(principal.user_id, statuses or [], limit=MY_JOBS_LIMIT)
    wanted = {media_id for job in jobs for media_id in job.media_ids}
    refs = await media.refs(wanted) if wanted else {}
    return JobsOut(
        items=[
            JobOut.of(
                JobDetails(job=job, photos=photos_of(job.media_ids, refs, LARGE), client=None),
                owner=True,
            )
            for job in jobs
        ]
    )


async def _own(show: ShowJob, job_id: JobId, owner_id: UserId, response: Response) -> JobOut:
    details = await show(ShowJobCommand(job_id=job_id, viewer_id=owner_id))
    if details.job.client_id != owner_id:
        raise JobNotFoundError(job_id=job_id)
    set_etag(response, details.job.version)
    return JobOut.of(details, owner=True)


def _language(locale: Locale) -> str:
    """Язык текста заявки — язык интерфейса автора: ru или sr (обе письменности)."""
    return locale.value.split("-")[0]


@router.patch(
    "/responses/{response_id:uuid}", response_model=MyResponseOut, dependencies=AUTHENTICATED
)
@inject
async def revise_response(
    response_id: ResponsePath,
    body: ResponseIn,
    principal: FromDishka[Principal],
    revise: FromDishka[ReviseResponse],
    queries: FromDishka[JobQueries],
) -> MyResponseOut:
    """Поправить свой отклик, пока клиент не решил (иначе 409 `response_not_active`): новая
    редакция снова на проверке."""
    await revise(
        ReviseResponseCommand(
            actor_id=principal.user_id, response_id=ResponseId(response_id), offer=body.offer()
        )
    )
    return await _my_response(queries, principal.user_id, ResponseId(response_id))


@router.post(
    "/responses/{response_id:uuid}/withdraw",
    response_model=MyResponseOut,
    dependencies=AUTHENTICATED,
)
@inject
async def withdraw_response(
    response_id: ResponsePath,
    principal: FromDishka[Principal],
    withdraw: FromDishka[WithdrawResponse],
    queries: FromDishka[JobQueries],
) -> MyResponseOut:
    """Отозвать свой отклик, пока клиент не решил: место на заявке освобождается."""
    await withdraw(
        WithdrawResponseCommand(actor_id=principal.user_id, response_id=ResponseId(response_id))
    )
    return await _my_response(queries, principal.user_id, ResponseId(response_id))


@router.get("/me/responses", response_model=MyResponsesPageOut, dependencies=AUTHENTICATED)
@inject
async def list_my_responses(
    *,
    status_group: Annotated[
        ResponseGroup | None,
        Query(
            alias="status",
            description="Чип S17: active, accepted, not_selected, archive; без него — все",
        ),
    ] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MY_RESPONSES_LIMIT)] = DEFAULT_LIMIT,
    principal: FromDishka[Principal],
    responses: FromDishka[ListMyResponses],
) -> MyResponsesPageOut:
    """Мои отклики (S17), новые первыми, с заявкой; числа на чипах и «сегодня откликов: 3 из
    50»."""
    found = await responses(
        ListMyResponsesCommand(
            actor_id=principal.user_id,
            trust_level=principal.trust_level,
            group=status_group,
            page=PageRequest(cursor=cursor, limit=limit),
        )
    )
    return MyResponsesPageOut(
        items=[MyResponseOut.of(item) for item in found.page.items],
        next_cursor=found.page.next_cursor,
        counts=ResponseCountsOut.of(found.counts),
        today=TodayOut.of(found.today),
    )


@router.get(
    "/jobs/{job_id:uuid}/responses", response_model=JobResponsesOut, dependencies=AUTHENTICATED
)
@inject
async def list_job_responses(
    job_id: JobPath, principal: FromDishka[Principal], responses: FromDishka[ListJobResponses]
) -> JobResponsesOut:
    """Отклики на свою заявку (S23): прошедшие проверку, по порядку, с «Откликнулся первым».
    Чужая заявка — 404."""
    listed = await responses(
        ListJobResponsesCommand(actor_id=principal.user_id, job_id=JobId(job_id))
    )
    return JobResponsesOut(items=[JobResponseOut.of(item) for item in listed])


async def _my_response(
    queries: JobQueries, user_id: UserId, response_id: ResponseId
) -> MyResponseOut:
    found = await queries.my_response(user_id, response_id)
    if found is None:
        raise ResponseNotFoundError(response_id=response_id)
    return MyResponseOut.of(found)
