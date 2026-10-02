"""Репозиторий заявок (ADR-0020 §5): заявка с фото — один агрегат, переходы статусов — в
`jobs.status_history` при каждом сохранении."""

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.domain.job import (
    Budget,
    Job,
    JobContent,
    JobId,
    Place,
)
from app.modules.jobs.errors import JobNotFoundError
from app.modules.jobs.infrastructure.models import JobMediaRow, JobRow, StatusHistoryRow
from app.platform.db.port import UnitOfWork
from app.platform.db.versioning import check_loaded_version
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId


class SqlJobRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def add(self, job: Job) -> None:
        self._uow.require_active()
        row = JobRow(id=job.id, version=job.version, created_at=job.created_at)
        _apply(job, row)
        self._session.add(row)
        await self._session.flush()
        await self._replace_media(job)
        self._add_history(job)
        await self._session.flush()
        self._uow.track(job)

    async def get_for_update(self, job_id: JobId) -> Job:
        self._uow.require_active()
        stmt = (
            select(JobRow)
            .where(JobRow.id == job_id, JobRow.deleted_at.is_(None))
            .with_for_update(of=JobRow)
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise JobNotFoundError(job_id=job_id)
        media = (
            await self._session.execute(
                select(JobMediaRow.media_id)
                .where(JobMediaRow.job_id == row.id)
                .order_by(JobMediaRow.position)
            )
        ).scalars()
        job = _to_domain(row, tuple(MediaId(m) for m in media))
        self._uow.track(job)
        return job

    async def save(self, job: Job) -> None:
        self._uow.require_active()
        row = await self._session.get(JobRow, job.id)
        if row is None:
            raise JobNotFoundError(job_id=job.id)
        check_loaded_version(entity="job", loaded=row.version, expected=job.version)
        _apply(job, row)
        row.version = job.version + 1
        await self._session.flush()
        await self._replace_media(job)
        self._add_history(job)
        await self._session.flush()
        job.mark_persisted(version=row.version)
        self._uow.track(job)

    async def of_client(self, client_id: UserId) -> list[JobId]:
        self._uow.require_active()
        stmt = select(JobRow.id).where(JobRow.client_id == client_id, JobRow.deleted_at.is_(None))
        return [JobId(value) for value in (await self._session.scalars(stmt)).all()]

    async def forget_private(self, client_id: UserId) -> None:
        self._uow.require_active()
        await self._session.execute(
            update(JobRow)
            .where(
                JobRow.client_id == client_id,
                or_(JobRow.point_exact.is_not(None), JobRow.address_private.is_not(None)),
            )
            .values(point_exact=None, address_private=None)
            .execution_options(synchronize_session=False)
        )

    async def _replace_media(self, job: Job) -> None:
        await self._session.execute(delete(JobMediaRow).where(JobMediaRow.job_id == job.id))
        self._session.add_all(
            JobMediaRow(job_id=job.id, media_id=media_id, position=index)
            for index, media_id in enumerate(job.content.media_ids)
        )

    def _add_history(self, job: Job) -> None:
        self._session.add_all(
            StatusHistoryRow(
                job_id=job.id,
                from_status=change.from_.value,
                to_status=change.to.value,
                actor_id=change.actor_id,
                actor_kind=kind,
                reason=change.reason,
                created_at=change.at,
            )
            for change, kind in job.pull_history()
        )


def _to_domain(row: JobRow, media: tuple[MediaId, ...]) -> Job:
    content = JobContent(
        title=row.title,
        description=row.description,
        category_id=CategoryId(row.category_id),
        category_path=tuple(CategoryId(c) for c in row.category_path),
        urgency=row.urgency,
        budget=Budget(
            type=row.budget_type, min=row.budget_min, max=row.budget_max, unit=row.budget_unit
        ),
        place=Place(
            city_id=CityId(row.city_id),
            district_id=DistrictId(row.district_id) if row.district_id is not None else None,
            point_exact=row.point_exact,
            point_public=row.point_public,
            address_private=row.address_private,
        ),
        content_lang=row.content_lang,
        preferred_from=row.preferred_from,
        preferred_to=row.preferred_to,
        languages=tuple(row.languages),
        media_ids=media,
    )
    return Job(
        id=JobId(row.id),
        client_id=UserId(row.client_id),
        content=content,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        visibility=row.visibility,
        source=row.source,
        max_responses=row.max_responses,
        responses_count=row.responses_count,
        extensions_count=row.extensions_count,
        published_at=row.published_at,
        expires_at=row.expires_at,
        closed_at=row.closed_at,
        close_reason=row.close_reason,
        moderation_note=row.moderation_note,
        expiry_reminded_at=row.expiry_reminded_at,
        deleted_at=row.deleted_at,
        version=row.version,
    )


def _apply(job: Job, row: JobRow) -> None:
    content, place, budget = job.content, job.content.place, job.content.budget
    row.client_id = job.client_id
    row.status = job.status
    row.visibility = job.visibility
    row.title = content.title
    row.description = content.description
    row.content_lang = content.content_lang
    row.category_id = content.category_id
    row.category_path = list(content.category_path)
    row.urgency = content.urgency
    row.preferred_from = content.preferred_from
    row.preferred_to = content.preferred_to
    row.budget_type = budget.type
    row.budget_min = budget.min
    row.budget_max = budget.max
    row.budget_unit = budget.unit
    row.city_id = place.city_id
    row.district_id = place.district_id
    row.point_exact = place.point_exact
    row.point_public = place.point_public
    row.address_private = place.address_private
    row.languages = list(content.languages)
    row.max_responses = job.max_responses
    row.responses_count = job.responses_count
    row.extensions_count = job.extensions_count
    row.source = job.source
    row.moderation_note = job.moderation_note
    row.published_at = job.published_at
    row.expires_at = job.expires_at
    row.expiry_reminded_at = job.expiry_reminded_at
    row.closed_at = job.closed_at
    row.close_reason = job.close_reason
    row.updated_at = job.updated_at
    row.deleted_at = job.deleted_at
