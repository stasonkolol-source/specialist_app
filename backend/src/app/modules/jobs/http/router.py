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
- `POST /jobs/{id}/hide` — «не подходит»: заявка пропадает из ленты этого исполнителя.
- `GET /me/favorites/jobs`, `PUT` и `DELETE /me/favorites/job/{id}` — сохранённые заявки
  (сердечко S15, сегмент «Задачи» S12): открытые, новые первыми, до ста (`saved_jobs_full`).
- Отклики (5.4): `POST /jobs/{id}/responses` (Idempotency-Key) — пять мест на заявку под
  блокировкой её строки, суточный лимит по уровню доверия; `GET /responses/{id}` — свой отклик
  с заявкой (правка на S16); `PATCH /responses/{id}`, `POST /responses/{id}/withdraw` —
  исполнителю, пока клиент не решил; `GET /me/responses` —
  «Мои отклики» S17; `GET /jobs/{id}/responses` — владельцу заявки (S23).
- Шаблоны откликов (5.5): `GET`, `POST` (Idempotency-Key), `PATCH` и `DELETE
  /me/response-templates` — до двух, первый — основной; отклик из шаблона несёт `template_id`.
- Приглашения и прямой запрос (5.6): `POST` и `GET /jobs/{id}/invites` — владельцу, до десяти
  специалистов; `POST /specialists/{id}/requests` (Idempotency-Key) — заявка с
  `visibility = direct`, видна только приглашённому. Открытие заявки не владельцем считается
  просмотром (`views_count` — владельцу).
- Подписки на новые заявки (5.7): `GET`, `POST` (Idempotency-Key), `PATCH` и `DELETE
  /me/job-alerts` — http/alerts.py; лента и счётчик с `feed=alerts` — только заявки, подходящие
  включённым подпискам вошедшего (гостю — 401).
- Выбор исполнителя (6.1a): `POST /responses/{id}/accept` — отклик принят, остальные «не
  выбран», заявка «в работе», в той же транзакции — сделка `agreed` (deals); `…/shortlist` —
  «в избранные»; `…/decline` — отклонить, место освобождается. Только владельцу заявки и только
  видимый ему активный отклик; чужой — 404.
Лимиты новичка — в use case (§13.3); лента и счётчик — 60 / 120 запросов в минуту.
"""

from dataclasses import replace
from typing import Annotated, Final, Literal
from uuid import UUID

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Response, status

from app.modules.jobs.application.feed import FeedFilters
from app.modules.jobs.application.photos import LARGE, photos_of
from app.modules.jobs.application.ports import JobQueries
from app.modules.jobs.application.responses import ResponseGroup
from app.modules.jobs.application.use_cases.accept_response import (
    AcceptResponse,
    AcceptResponseCommand,
)
from app.modules.jobs.application.use_cases.browse_jobs import BrowseJobs, BrowseJobsCommand
from app.modules.jobs.application.use_cases.close_job import CloseJob, CloseJobCommand
from app.modules.jobs.application.use_cases.count_job_view import (
    CountJobView,
    CountJobViewCommand,
)
from app.modules.jobs.application.use_cases.count_jobs import CountJobs, CountJobsCommand
from app.modules.jobs.application.use_cases.create_job import CreateJob, CreateJobCommand
from app.modules.jobs.application.use_cases.create_template import (
    CreateTemplate,
    CreateTemplateCommand,
)
from app.modules.jobs.application.use_cases.decline_response import (
    DeclineResponse,
    DeclineResponseCommand,
)
from app.modules.jobs.application.use_cases.delete_job import DeleteJob, DeleteJobCommand
from app.modules.jobs.application.use_cases.delete_template import (
    DeleteTemplate,
    DeleteTemplateCommand,
)
from app.modules.jobs.application.use_cases.edit_job import EditJob, EditJobCommand
from app.modules.jobs.application.use_cases.extend_job import ExtendJob, ExtendJobCommand
from app.modules.jobs.application.use_cases.hide_job import HideJob, HideJobCommand
from app.modules.jobs.application.use_cases.invite_specialists import (
    InviteSpecialists,
    InviteSpecialistsCommand,
)
from app.modules.jobs.application.use_cases.list_job_invites import (
    ListJobInvites,
    ListJobInvitesCommand,
)
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
from app.modules.jobs.application.use_cases.list_templates import (
    ListTemplates,
    ListTemplatesCommand,
)
from app.modules.jobs.application.use_cases.respond import Respond, RespondCommand
from app.modules.jobs.application.use_cases.revise_response import (
    ReviseResponse,
    ReviseResponseCommand,
)
from app.modules.jobs.application.use_cases.save_job import SaveJob, SaveJobCommand
from app.modules.jobs.application.use_cases.shortlist_response import (
    ShortlistResponse,
    ShortlistResponseCommand,
)
from app.modules.jobs.application.use_cases.show_job import JobDetails, ShowJob, ShowJobCommand
from app.modules.jobs.application.use_cases.unsave_job import UnsaveJob, UnsaveJobCommand
from app.modules.jobs.application.use_cases.update_template import (
    UpdateTemplate,
    UpdateTemplateCommand,
)
from app.modules.jobs.application.use_cases.withdraw_response import (
    WithdrawResponse,
    WithdrawResponseCommand,
)
from app.modules.jobs.domain.job import MAX_BUDGET, CloseReason, JobId, JobStatus, Urgency
from app.modules.jobs.domain.response import ResponseId
from app.modules.jobs.domain.template import TemplateId
from app.modules.jobs.errors import JobNotFoundError, ResponseNotFoundError
from app.modules.jobs.http.alerts import alerts
from app.modules.jobs.http.schemas import (
    AcceptedOut,
    InvitesIn,
    JobCardOut,
    JobCloseIn,
    JobIn,
    JobInvitesOut,
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
    ResponseOfferIn,
    ResponseTemplateIn,
    ResponseTemplateOut,
    ResponseTemplatePatchIn,
    ResponseTemplatesOut,
    SavedJobsOut,
    TodayOut,
)
from app.modules.media.api import MediaApi
from app.platform.http.concurrency import IfMatch, set_etag
from app.platform.http.fields import INT4_MAX, CategoryIdIn, DistrictIdIn
from app.platform.http.idempotency import idempotent_router
from app.platform.http.ratelimit import GuestOrUserRateLimit
from app.platform.http.security import AUTHENTICATED, optional_principal
from app.platform.kernel.errors import DomainValidationError, NotAuthenticatedError
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

log = structlog.get_logger(__name__)
router = APIRouter(tags=["jobs"])
creating = idempotent_router()
JobPath = Annotated[UUID, Path(description="id заявки")]
ResponsePath = Annotated[UUID, Path(description="id отклика")]
TemplatePath = Annotated[UUID, Path(description="id шаблона отклика")]
ProfilePath = Annotated[UUID, Path(description="id профиля специалиста")]
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
            template_id=TemplateId(body.template_id) if body.template_id else None,
        )
    )
    return await _my_response(queries, principal.user_id, response_id)


@creating.post(
    "/me/response-templates",
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseTemplateOut,
    dependencies=AUTHENTICATED,
)
@inject
async def create_response_template(
    body: ResponseTemplateIn, principal: FromDishka[Principal], create: FromDishka[CreateTemplate]
) -> ResponseTemplateOut:
    """Новый шаблон (S57, «Сохранить как шаблон» на S16): не больше двух — третий 409
    `response_templates_full`; первый — основной."""
    template = await create(
        CreateTemplateCommand(actor_id=principal.user_id, title=body.title, offer=body.offer())
    )
    return ResponseTemplateOut.of(template)


@creating.post(
    "/specialists/{profile_id:uuid}/requests",
    status_code=status.HTTP_201_CREATED,
    response_model=JobOut,
    dependencies=AUTHENTICATED,
)
@inject
async def request_specialist(
    profile_id: ProfilePath,
    body: JobIn,
    principal: FromDishka[Principal],
    locale: FromDishka[Locale],
    create: FromDishka[CreateJob],
    show: FromDishka[ShowJob],
    response: Response,
) -> JobOut:
    """Прямой запрос специалисту (S08 «Написать», S09 «Заказать эту услугу»): заявка, которую
    видит только он, — на проверку, как любая; после публикации ему уведомление. Профиль скрыт,
    удалён или автор под санкцией — 404 `invitee_not_found`; свой — 409 `own_profile_invite`."""
    job_id = await create(
        CreateJobCommand(
            actor_id=principal.user_id,
            trust_level=principal.trust_level,
            draft=body.draft(_language(locale)),
            direct_profile_id=profile_id,
        )
    )
    return await _own(show, job_id, principal.user_id, response)


router.include_router(creating)
router.include_router(alerts)


def feed_filters(
    *,
    city_id: Annotated[int, Query(ge=1, le=INT4_MAX, description="Город ленты")],
    category: Annotated[
        list[CategoryIdIn] | None,
        Query(description="Категории: с подкатегориями, любая из них"),
    ] = None,
    district: Annotated[
        list[DistrictIdIn] | None, Query(description="Районы: любой из них")
    ] = None,
    lat: Annotated[float | None, Query(ge=-90, le=90, description="Точка зрителя")] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[
        float | None, Query(gt=0, le=MAX_RADIUS_KM, description="Радиус от точки")
    ] = None,
    urgency: Annotated[list[Urgency] | None, Query()] = None,
    budget_from: Annotated[
        int | None,
        Query(ge=1, le=MAX_BUDGET, description="Пара: бюджет не меньше (договорные — нет)"),
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
FeedMode = Annotated[
    Literal["alerts"] | None,
    Query(description="alerts — «по моим подпискам» (5.7): только вошедшему"),
]


def _with_mode(
    filters: FeedFilters, feed: Literal["alerts"] | None, viewer: Principal | None
) -> FeedFilters:
    """«По моим подпискам» — заявки, подходящие включённым подпискам зрителя; гостю — 401."""
    if feed is None:
        return filters
    if viewer is None:
        raise NotAuthenticatedError
    return replace(filters, alerts_of=viewer.user_id)


@router.get("/jobs", response_model=JobsPageOut, dependencies=feed_limit)
@inject
async def list_jobs(
    filters: Feed,
    viewer: Viewer,
    browse: FromDishka[BrowseJobs],
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=FEED_MAX_LIMIT)] = DEFAULT_LIMIT,
    feed: FeedMode = None,
) -> JobsPageOut:
    """Лента 🔓 (S13): опубликованные заявки города, свежие сверху; свои и скрытые — нет;
    `feed=alerts` — по моим подпискам."""
    page = await browse(
        BrowseJobsCommand(
            filters=_with_mode(filters, feed, viewer),
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
    count: FromDishka[CountJobs],
    new_hours: Annotated[
        int | None, Query(ge=1, le=MAX_NEW_HOURS, description="Только опубликованные за часы")
    ] = None,
    feed: FeedMode = None,
) -> JobsCountOut:
    """Сколько заявок с фильтрами 🔓: «Показать N» S14, «N новых задач рядом» на Главной;
    `feed=alerts` — по моим подпискам."""
    found = await count(
        CountJobsCommand(
            filters=_with_mode(filters, feed, viewer),
            viewer_id=viewer.user_id if viewer is not None else None,
            new_hours=new_hours,
        )
    )
    return JobsCountOut(count=found)


@router.get("/jobs/{job_id:uuid}", response_model=JobOut)
@inject
async def get_job(
    job_id: JobPath,
    viewer: Viewer,
    show: FromDishka[ShowJob],
    count_view: FromDishka[CountJobView],
    response: Response,
    background: BackgroundTasks,
) -> JobOut:
    """Заявка 🔓: опубликованная — всем без точной точки и адреса, своя — владельцу целиком;
    прямой запрос — только приглашённому. Вошедший не владелец — просмотр (раз в сутки)."""
    viewer_id = viewer.user_id if viewer is not None else None
    details = await show(ShowJobCommand(job_id=JobId(job_id), viewer_id=viewer_id))
    owner = viewer_id == details.job.client_id
    if owner:
        set_etag(response, details.job.version)
    elif viewer_id is not None and details.job.status is JobStatus.PUBLISHED:
        # счётчик просмотров — после ответа: ответ не ждёт лимитера и UPDATE с COMMIT
        background.add_task(
            _count_view, count_view, CountJobViewCommand(job_id=JobId(job_id), viewer_id=viewer_id)
        )
    return JobOut.of(details, owner=owner)


async def _count_view(count_view: CountJobView, command: CountJobViewCommand) -> None:
    """Просмотр — аналитика S23: ответ уже ушёл, сбой счётчика только пишется в лог."""
    try:
        await count_view(command)
    except Exception as exc:  # noqa: BLE001 — потерянный просмотр не ошибка запроса
        log.warning("job_view_not_counted", job_id=str(command.job_id), error=type(exc).__name__)


@router.post(
    "/jobs/{job_id:uuid}/hide",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=AUTHENTICATED,
)
@inject
async def hide_job(
    job_id: JobPath, principal: FromDishka[Principal], hide: FromDishka[HideJob]
) -> None:
    """«Не подходит» (S15): заявка пропадает из ленты; повтор — без ошибки."""
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
    """Свои заявки (S22), новые первыми, с числом новых откликов; блока клиента в своём списке
    нет."""
    jobs = await queries.own(principal.user_id, statuses or [], limit=MY_JOBS_LIMIT)
    wanted = {media_id for job in jobs for media_id in job.media_ids}
    refs = await media.refs(wanted) if wanted else {}
    fresh = await queries.unseen_counts([job.id for job in jobs])
    return JobsOut(
        items=[
            JobOut.of(
                JobDetails(
                    job=job,
                    photos=photos_of(job.media_ids, refs, LARGE),
                    client=None,
                    new_responses=fresh.get(job.id, 0),
                ),
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


@router.get(
    "/responses/{response_id:uuid}", response_model=MyResponseOut, dependencies=AUTHENTICATED
)
@inject
async def get_response(
    response_id: ResponsePath, principal: FromDishka[Principal], queries: FromDishka[JobQueries]
) -> MyResponseOut:
    """Свой отклик с заявкой — форма правки S16; чужой — 404."""
    return await _my_response(queries, principal.user_id, ResponseId(response_id))


@router.patch(
    "/responses/{response_id:uuid}", response_model=MyResponseOut, dependencies=AUTHENTICATED
)
@inject
async def revise_response(
    response_id: ResponsePath,
    body: ResponseOfferIn,
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


@router.post(
    "/responses/{response_id:uuid}/accept", response_model=AcceptedOut, dependencies=AUTHENTICATED
)
@inject
async def accept_response(
    response_id: ResponsePath,
    principal: FromDishka[Principal],
    accept: FromDishka[AcceptResponse],
    show: FromDishka[ShowJob],
    response: Response,
) -> AcceptedOut:
    """Выбрать исполнителем: создана сделка `agreed`, заявка «в работе», остальные отклики — «не
    выбран». Заявка не опубликована или отклик уже решён — 409."""
    accepted = await accept(
        AcceptResponseCommand(actor_id=principal.user_id, response_id=ResponseId(response_id))
    )
    job = await _own(show, accepted.job_id, principal.user_id, response)
    return AcceptedOut(deal_id=accepted.deal_id, job=job)


@router.post(
    "/responses/{response_id:uuid}/shortlist", response_model=JobOut, dependencies=AUTHENTICATED
)
@inject
async def shortlist_response(
    response_id: ResponsePath,
    principal: FromDishka[Principal],
    shortlist: FromDishka[ShortlistResponse],
    show: FromDishka[ShowJob],
    response: Response,
) -> JobOut:
    """«В избранные»: отклик среди лучших кандидатов; повтор — без изменений."""
    job_id = await shortlist(
        ShortlistResponseCommand(actor_id=principal.user_id, response_id=ResponseId(response_id))
    )
    return await _own(show, job_id, principal.user_id, response)


@router.post(
    "/responses/{response_id:uuid}/decline", response_model=JobOut, dependencies=AUTHENTICATED
)
@inject
async def decline_response(
    response_id: ResponsePath,
    principal: FromDishka[Principal],
    decline: FromDishka[DeclineResponse],
    show: FromDishka[ShowJob],
    response: Response,
) -> JobOut:
    """Отклонить отклик: место на заявке освобождается."""
    job_id = await decline(
        DeclineResponseCommand(actor_id=principal.user_id, response_id=ResponseId(response_id))
    )
    return await _own(show, job_id, principal.user_id, response)


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


@router.get(
    "/me/response-templates", response_model=ResponseTemplatesOut, dependencies=AUTHENTICATED
)
@inject
async def list_response_templates(
    principal: FromDishka[Principal], templates: FromDishka[ListTemplates]
) -> ResponseTemplatesOut:
    """Шаблоны откликов (S57, S16): по порядку, первый — основной."""
    return ResponseTemplatesOut.of(
        await templates(ListTemplatesCommand(actor_id=principal.user_id))
    )


@router.patch(
    "/me/response-templates/{template_id:uuid}",
    response_model=ResponseTemplateOut,
    dependencies=AUTHENTICATED,
)
@inject
async def update_response_template(
    template_id: TemplatePath,
    body: ResponseTemplatePatchIn,
    principal: FromDishka[Principal],
    update: FromDishka[UpdateTemplate],
) -> ResponseTemplateOut:
    """Поправить шаблон (S57) или сделать основным (`primary: true`); чужой — 404."""
    template = await update(
        UpdateTemplateCommand(
            actor_id=principal.user_id,
            template_id=TemplateId(template_id),
            title=body.title,
            offer=body.offer(),
            primary=body.primary,
        )
    )
    return ResponseTemplateOut.of(template)


@router.delete(
    "/me/response-templates/{template_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=AUTHENTICATED,
)
@inject
async def delete_response_template(
    template_id: TemplatePath, principal: FromDishka[Principal], delete: FromDishka[DeleteTemplate]
) -> None:
    """Удалить шаблон (S57): основным становится следующий; чужой — 404."""
    await delete(
        DeleteTemplateCommand(actor_id=principal.user_id, template_id=TemplateId(template_id))
    )


async def _my_response(
    queries: JobQueries, user_id: UserId, response_id: ResponseId
) -> MyResponseOut:
    found = await queries.my_response(user_id, response_id)
    if found is None:
        raise ResponseNotFoundError(response_id=response_id)
    return MyResponseOut.of(found)


@router.post(
    "/jobs/{job_id:uuid}/invites", response_model=JobInvitesOut, dependencies=AUTHENTICATED
)
@inject
async def invite_specialists(
    job_id: JobPath,
    body: InvitesIn,
    principal: FromDishka[Principal],
    invite: FromDishka[InviteSpecialists],
) -> JobInvitesOut:
    """Пригласить специалистов в свою открытую заявку (S21, S23): им — уведомление с «Посмотреть
    заявку» и «Откликнуться шаблоном». Повтор — без ошибки; больше десяти — 409 `job_invites_full`;
    скрытый профиль или автор под санкцией — 404 `invitee_not_found`."""
    invites = await invite(
        InviteSpecialistsCommand(
            actor_id=principal.user_id, job_id=JobId(job_id), profile_ids=body.profile_ids
        )
    )
    return JobInvitesOut.of(invites)


@router.get("/jobs/{job_id:uuid}/invites", response_model=JobInvitesOut, dependencies=AUTHENTICATED)
@inject
async def list_job_invites(
    job_id: JobPath, principal: FromDishka[Principal], invites: FromDishka[ListJobInvites]
) -> JobInvitesOut:
    """Кого владелец пригласил в заявку (S23), по порядку. Чужая — 404."""
    found = await invites(ListJobInvitesCommand(actor_id=principal.user_id, job_id=JobId(job_id)))
    return JobInvitesOut.of(found)
