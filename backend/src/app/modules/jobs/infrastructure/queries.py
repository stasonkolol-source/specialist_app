"""Чтение заявок (экраны S15, S22, S23, лимит активных, сроки): без блокировок, сессия
освобождается после запроса (SqlQuery)."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Integer,
    RowMapping,
    String,
    and_,
    cast,
    exists,
    func,
    literal,
    or_,
    select,
    text,
    tuple_,
)
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by

from app.modules.jobs.application.dto import JobView
from app.modules.jobs.application.feed import (
    CARD_PHOTOS,
    DESCRIPTION_PREVIEW,
    FeedFilters,
    FeedItem,
)
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
from app.modules.jobs.infrastructure.models import HiddenJobRow, JobMediaRow, JobRow
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.db.types import GeoPointType
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId
from app.platform.kernel.pagination import Page, PageRequest

_J = JobRow.__table__.c
_M = JobMediaRow.__table__.c
_H = HiddenJobRow.__table__.c
_OPEN = and_(_J.status == JobStatus.PUBLISHED.value, _J.deleted_at.is_(None))
"""Опубликованная и не удалённая: частичный индекс ix_jobs_expires_at."""
DISTANCE_STEP_M = 100
"""Расстояние в карточке — шагом 100 м: точку заявки и так сместили на 300–500 м."""
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

    async def feed(
        self,
        filters: FeedFilters,
        *,
        viewer_id: UserId | None,
        page: PageRequest,
        now: datetime,
    ) -> Page[FeedItem]:
        point = literal(filters.near, GeoPointType) if filters.near is not None else None
        distance = (
            func.ST_Distance(_J.point_public, point).label("distance")
            if point is not None
            else literal(None).label("distance")
        )
        stmt = select(
            _J.id,
            _J.title,
            func.left(_J.description, DESCRIPTION_PREVIEW + 1).label("description"),
            _J.category_id,
            _J.urgency,
            _J.preferred_from,
            _J.preferred_to,
            _J.budget_type,
            _J.budget_min,
            _J.budget_max,
            _J.budget_unit,
            _J.district_id,
            _J.responses_count,
            _J.max_responses,
            _J.published_at,
            distance,
            _MEDIA_IDS,
        ).where(*_feed_conditions(filters, viewer_id, now))
        if page.cursor is not None:
            published_at, job_id = decode_cursor(page.cursor, (datetime, UUID))
            stmt = stmt.where(tuple_(_J.published_at, _J.id) < tuple_(published_at, job_id))
        rows = await self._fetch(
            stmt.order_by(_J.published_at.desc(), _J.id.desc()).limit(page.limit + 1)
        )
        items = [_feed_item(row) for row in rows[: page.limit]]
        more = len(rows) > page.limit
        last = items[-1] if items else None
        cursor = encode_cursor(last.published_at, last.id) if more and last else None
        return Page(items=tuple(items), next_cursor=cursor)

    async def feed_count(
        self, filters: FeedFilters, *, viewer_id: UserId | None, now: datetime
    ) -> int:
        row = await self._fetch_one(
            select(func.count().label("count")).where(*_feed_conditions(filters, viewer_id, now))
        )
        return int(row["count"]) if row is not None else 0

    async def count_published(self, client_id: UserId) -> int:
        row = await self._fetch_one(
            select(func.count().label("count")).where(
                _J.client_id == client_id, _J.published_at.is_not(None)
            )
        )
        return int(row["count"]) if row is not None else 0

    async def count_active(self, client_id: UserId) -> int:
        row = await self._fetch_one(
            select(func.count().label("count")).where(
                _J.client_id == client_id,
                _J.deleted_at.is_(None),
                _J.status.in_([status.value for status in ACTIVE]),
            )
        )
        return int(row["count"]) if row is not None else 0


def _feed_conditions(
    filters: FeedFilters, viewer_id: UserId | None, now: datetime
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [
        _OPEN,
        _J.visibility == Visibility.PUBLIC.value,
        _J.city_id == filters.city_id,
        or_(_J.expires_at.is_(None), _J.expires_at > now),
    ]
    if viewer_id is not None:
        conditions.append(_J.client_id != viewer_id)
        conditions.append(~exists().where(_H.user_id == viewer_id, _H.job_id == _J.id))
    if filters.category_ids:
        wanted = cast(list(filters.category_ids), ARRAY(Integer))
        conditions.append(_J.category_path.overlap(wanted))
    if filters.district_ids:
        conditions.append(_J.district_id.in_(filters.district_ids))
    if filters.near is not None and filters.radius_m is not None:
        point = literal(filters.near, GeoPointType)
        conditions.append(func.ST_DWithin(_J.point_public, point, filters.radius_m))
    if filters.urgencies:
        conditions.append(_J.urgency.in_([urgency.value for urgency in filters.urgencies]))
    if filters.budget_from is not None:
        conditions.append(func.coalesce(_J.budget_max, _J.budget_min) >= filters.budget_from)
    if filters.languages:
        wanted_languages = cast(list(filters.languages), ARRAY(String(8)))
        conditions.append(
            or_(func.cardinality(_J.languages) == 0, _J.languages.overlap(wanted_languages))
        )
    if filters.with_photos:
        conditions.append(exists().where(_M.job_id == _J.id))
    if filters.published_after is not None:
        conditions.append(_J.published_at >= filters.published_after)
    return conditions


def _feed_item(row: RowMapping) -> FeedItem:
    district = row["district_id"]
    distance = row["distance"]
    media = tuple(MediaId(value) for value in row["media_ids"])
    description = row["description"]
    if len(description) > DESCRIPTION_PREVIEW:
        description = description[:DESCRIPTION_PREVIEW].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
    return FeedItem(
        id=JobId(row["id"]),
        title=row["title"],
        description=description,
        category_id=CategoryId(row["category_id"]),
        urgency=Urgency(row["urgency"]),
        preferred_from=row["preferred_from"],
        preferred_to=row["preferred_to"],
        budget_type=BudgetType(row["budget_type"]),
        budget_min=row["budget_min"],
        budget_max=row["budget_max"],
        budget_unit=BudgetUnit(row["budget_unit"]),
        district_id=DistrictId(district) if district is not None else None,
        distance_m=_rounded(distance),
        media_ids=media[:CARD_PHOTOS],
        photos_count=len(media),
        responses_count=row["responses_count"],
        max_responses=row["max_responses"],
        published_at=row["published_at"],
    )


def _rounded(distance: float | None) -> int | None:
    if distance is None:
        return None
    return max(DISTANCE_STEP_M, round(distance / DISTANCE_STEP_M) * DISTANCE_STEP_M)


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
