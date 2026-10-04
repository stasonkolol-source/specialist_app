"""Сроки хранения заявок (2.12b): выборка просроченных и физическое удаление с откликами."""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.domain.job import JobId, JobStatus
from app.modules.jobs.domain.response import ResponseId
from app.modules.jobs.infrastructure.models import (
    HiddenJobRow,
    InviteRow,
    JobMediaRow,
    JobRow,
    ResponseRow,
    SavedJobRow,
    StatusHistoryRow,
)
from app.platform.kernel.ids import MediaId, UserId

CLOSED = (JobStatus.CLOSED, JobStatus.COMPLETED, JobStatus.EXPIRED, JobStatus.REMOVED)


class SqlJobRetention:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def expired(
        self,
        *,
        closed_before: datetime,
        rejected_before: datetime,
        after: JobId | None,
        limit: int,
    ) -> list[JobId]:
        # конец жизни заявки: закрытие, а у истёкшей — срок (её ещё можно было продлить)
        ended = func.coalesce(JobRow.closed_at, JobRow.expires_at, JobRow.updated_at)
        stmt = (
            select(JobRow.id)
            .where(
                or_(
                    and_(JobRow.status.in_(CLOSED), ended < closed_before),
                    and_(JobRow.status == JobStatus.REJECTED, JobRow.updated_at < rejected_before),
                )
            )
            .order_by(JobRow.id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(JobRow.id > after)
        return [JobId(job_id) for job_id in (await self._session.scalars(stmt)).all()]

    async def responses(self, job_ids: Collection[JobId]) -> dict[ResponseId, JobId]:
        if not job_ids:
            return {}
        rows = await self._session.execute(
            select(ResponseRow.id, ResponseRow.job_id).where(ResponseRow.job_id.in_(job_ids))
        )
        return {ResponseId(response_id): JobId(job_id) for response_id, job_id in rows}

    async def photos(self, job_ids: Collection[JobId]) -> list[tuple[UserId, MediaId]]:
        if not job_ids:
            return []
        rows = await self._session.execute(
            select(JobRow.client_id, JobMediaRow.media_id)
            .join(JobRow, JobRow.id == JobMediaRow.job_id)
            .where(JobMediaRow.job_id.in_(job_ids))
        )
        return [(UserId(owner_id), MediaId(media_id)) for owner_id, media_id in rows]

    async def purge(self, job_ids: Collection[JobId]) -> None:
        if not job_ids:
            return
        ids = list(job_ids)
        for model in (ResponseRow, InviteRow, SavedJobRow, HiddenJobRow, StatusHistoryRow):
            await self._session.execute(delete(model).where(model.job_id.in_(ids)))
        await self._session.execute(delete(JobMediaRow).where(JobMediaRow.job_id.in_(ids)))
        await self._session.execute(delete(JobRow).where(JobRow.id.in_(ids)))
