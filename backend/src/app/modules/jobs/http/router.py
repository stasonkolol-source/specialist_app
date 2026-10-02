"""HTTP jobs (DEVELOPMENT_PLAN 5.1; ARCHITECTURE §8.5): заявка клиента от создания до закрытия.

- `POST /jobs` (Idempotency-Key) — сразу на проверку: ответ `pending_moderation` (модерация
  публикует асинхронно) или уже `published`. `POST /jobs/{id}/submit` из §8.5 нет: черновик
  живёт только на клиенте (5.2).
- `GET /jobs/{id}` 🔓 — гость и исполнитель видят опубликованную, без точной точки и адреса;
  владелец — свою в любом статусе (`viewer_role: owner`), с ETag для If-Match.
- `PATCH /jobs/{id}` (If-Match → 412), `POST /jobs/{id}/close`, `POST /jobs/{id}/extend`,
  `DELETE /jobs/{id}` — только владелец; чужая заявка — 404.
- `GET /me/jobs?status=` — свои заявки, новые первыми.
Лимиты новичка — в use case (§13.3).
"""

from typing import Annotated, Final
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.modules.jobs.application.ports import JobQueries
from app.modules.jobs.application.use_cases.close_job import CloseJob, CloseJobCommand
from app.modules.jobs.application.use_cases.create_job import CreateJob, CreateJobCommand
from app.modules.jobs.application.use_cases.delete_job import DeleteJob, DeleteJobCommand
from app.modules.jobs.application.use_cases.edit_job import EditJob, EditJobCommand
from app.modules.jobs.application.use_cases.extend_job import ExtendJob, ExtendJobCommand
from app.modules.jobs.domain.job import CloseReason, JobId, JobStatus
from app.modules.jobs.domain.policies import can_view
from app.modules.jobs.errors import JobNotFoundError
from app.modules.jobs.http.schemas import JobCloseIn, JobIn, JobOut, JobsOut
from app.platform.http.concurrency import IfMatch, set_etag
from app.platform.http.idempotency import idempotent_router
from app.platform.http.security import AUTHENTICATED, optional_principal
from app.platform.kernel.ids import UserId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal

MY_JOBS_LIMIT: Final = 50

router = APIRouter(tags=["jobs"])
creating = idempotent_router()
JobPath = Annotated[UUID, Path(description="id заявки")]
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
    queries: FromDishka[JobQueries],
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
    return await _own(queries, job_id, principal.user_id, response)


router.include_router(creating)


@router.get("/jobs/{job_id}", response_model=JobOut)
@inject
async def get_job(
    job_id: JobPath, viewer: Viewer, queries: FromDishka[JobQueries], response: Response
) -> JobOut:
    """Заявка 🔓: опубликованная — всем без точной точки и адреса, своя — владельцу целиком."""
    viewer_id = viewer.user_id if viewer is not None else None
    job = await queries.view(JobId(job_id))
    if job is None or not can_view(client_id=job.client_id, status=job.status, viewer_id=viewer_id):
        raise JobNotFoundError(job_id=job_id)
    owner = viewer_id == job.client_id
    if owner:
        set_etag(response, job.version)
    return JobOut.of(job, owner=owner)


@router.patch("/jobs/{job_id}", response_model=JobOut, dependencies=AUTHENTICATED)
@inject
async def update_job(
    job_id: JobPath,
    body: JobIn,
    expected_version: IfMatch,
    principal: FromDishka[Principal],
    locale: FromDishka[Locale],
    edit: FromDishka[EditJob],
    queries: FromDishka[JobQueries],
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
    return await _own(queries, JobId(job_id), principal.user_id, response)


@router.post("/jobs/{job_id}/close", response_model=JobOut, dependencies=AUTHENTICATED)
@inject
async def close_job(
    job_id: JobPath,
    body: JobCloseIn,
    principal: FromDishka[Principal],
    close: FromDishka[CloseJob],
    queries: FromDishka[JobQueries],
    response: Response,
) -> JobOut:
    """Закрыть с причиной: нашёл здесь, нашёл в другом месте, уже не нужно, не подошли."""
    await close(
        CloseJobCommand(
            actor_id=principal.user_id, job_id=JobId(job_id), reason=CloseReason(body.reason)
        )
    )
    return await _own(queries, JobId(job_id), principal.user_id, response)


@router.post("/jobs/{job_id}/extend", response_model=JobOut, dependencies=AUTHENTICATED)
@inject
async def extend_job(
    job_id: JobPath,
    principal: FromDishka[Principal],
    extend: FromDishka[ExtendJob],
    queries: FromDishka[JobQueries],
    response: Response,
) -> JobOut:
    """Продлить опубликованную или переопубликовать истёкшую; четвёртый раз — 409."""
    await extend(ExtendJobCommand(actor_id=principal.user_id, job_id=JobId(job_id)))
    return await _own(queries, JobId(job_id), principal.user_id, response)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=AUTHENTICATED)
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
    statuses: Annotated[
        list[JobStatus] | None, Query(alias="status", description="Без фильтра — все")
    ] = None,
) -> JobsOut:
    """Свои заявки (S22), новые первыми."""
    jobs = await queries.own(principal.user_id, statuses or [], limit=MY_JOBS_LIMIT)
    return JobsOut(items=[JobOut.of(job, owner=True) for job in jobs])


async def _own(queries: JobQueries, job_id: JobId, owner_id: UserId, response: Response) -> JobOut:
    job = await queries.view(job_id)
    if job is None or job.client_id != owner_id:
        raise JobNotFoundError(job_id=job_id)
    set_etag(response, job.version)
    return JobOut.of(job, owner=True)


def _language(locale: Locale) -> str:
    """Язык текста заявки — язык интерфейса автора: ru или sr (обе письменности)."""
    return locale.value.split("-")[0]
