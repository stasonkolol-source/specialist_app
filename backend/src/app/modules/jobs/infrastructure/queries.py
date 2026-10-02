"""Чтение заявок (экраны S15, S22, S23, лимит активных, сроки): без блокировок, сессия
освобождается после запроса (SqlQuery)."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import RowMapping, and_, func, select, text
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.modules.jobs.application.dto import JobView
from app.modules.jobs.domain.job import (
    ACTIVE,
    BudgetType,
    BudgetUnit,
    CloseReason,
    JobId,
    JobStatus,
    Urgency,
    Visibility,
)
from app.modules.jobs.infrastructure.models import JobMediaRow, JobRow
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId

_J = JobRow.__table__.c
_M = JobMediaRow.__table__.c
_OPEN = and_(_J.status == JobStatus.PUBLISHED.value, _J.deleted_at.is_(None))
"""Опубликованная и не удалённая: частичный индекс ix_jobs_expires_at."""
_MEDIA_IDS = (
    select(
        func.coalesce(
            func.array_agg(aggregate_order_by(_M.media_id, _M.position)), text("'{}'::uuid[]")
        )
    )
    .where(_M.job_id == _J.id)
    .scalar_subquery()
    .label("media_ids")
)


class SqlJobQueries(SqlQuery):
    async def view(self, job_id: JobId) -> JobView | None:
        row = await self._fetch_one(
            select(*_J, _MEDIA_IDS).where(_J.id == job_id, _J.deleted_at.is_(None))
        )
        return _view(row) if row is not None else None

    async def own(
        self, client_id: UserId, statuses: Sequence[JobStatus], *, limit: int
    ) -> list[JobView]:
        stmt = select(*_J, _MEDIA_IDS).where(_J.client_id == client_id, _J.deleted_at.is_(None))
        if statuses:
            stmt = stmt.where(_J.status.in_([status.value for status in statuses]))
        rows = await self._fetch(stmt.order_by(_J.created_at.desc(), _J.id.desc()).limit(limit))
        return [_view(row) for row in rows]

    async def due_to_expire(self, now: datetime, *, limit: int) -> list[JobId]:
        rows = await self._fetch(
            select(_J.id)
            .where(_OPEN, _J.expires_at <= now)
            .order_by(_J.expires_at, _J.id)
            .limit(limit)
        )
        return [JobId(row["id"]) for row in rows]

    async def expiring(self, now: datetime, until: datetime, *, limit: int) -> list[JobId]:
        rows = await self._fetch(
            select(_J.id)
            .where(
                _OPEN,
                _J.expires_at > now,
                _J.expires_at <= until,
                _J.expiry_reminded_at.is_(None),
            )
            .order_by(_J.expires_at, _J.id)
            .limit(limit)
        )
        return [JobId(row["id"]) for row in rows]

    async def count_active(self, client_id: UserId) -> int:
        row = await self._fetch_one(
            select(func.count().label("count")).where(
                _J.client_id == client_id,
                _J.deleted_at.is_(None),
                _J.status.in_([status.value for status in ACTIVE]),
            )
        )
        return int(row["count"]) if row is not None else 0


def _view(row: RowMapping) -> JobView:
    district = row["district_id"]
    reason = row["close_reason"]
    return JobView(
        id=JobId(row["id"]),
        client_id=UserId(row["client_id"]),
        status=JobStatus(row["status"]),
        visibility=Visibility(row["visibility"]),
        title=row["title"],
        description=row["description"],
        content_lang=row["content_lang"],
        category_id=CategoryId(row["category_id"]),
        urgency=Urgency(row["urgency"]),
        preferred_from=row["preferred_from"],
        preferred_to=row["preferred_to"],
        budget_type=BudgetType(row["budget_type"]),
        budget_min=row["budget_min"],
        budget_max=row["budget_max"],
        budget_unit=BudgetUnit(row["budget_unit"]),
        city_id=CityId(row["city_id"]),
        district_id=DistrictId(district) if district is not None else None,
        point_exact=row["point_exact"],
        point_public=row["point_public"],
        address_private=row["address_private"],
        languages=tuple(row["languages"]),
        media_ids=tuple(MediaId(media) for media in row["media_ids"]),
        max_responses=row["max_responses"],
        responses_count=row["responses_count"],
        extensions_count=row["extensions_count"],
        moderation_note=row["moderation_note"],
        version=row["version"],
        created_at=row["created_at"],
        published_at=row["published_at"],
        expires_at=row["expires_at"],
        closed_at=row["closed_at"],
        close_reason=CloseReason(reason) if reason is not None else None,
    )
