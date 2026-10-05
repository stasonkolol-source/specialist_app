"""Чтение заявок (лента S13, экраны S12, S15, S22, S23, лимит активных, сроки): без блокировок,
сессия освобождается после запроса (SqlQuery)."""

from collections.abc import Collection, Sequence
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
    true,
    tuple_,
)
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by

from app.modules.jobs.application.dto import DealResponse, JobView, MyResponseRef
from app.modules.jobs.application.feed import (
    CARD_PHOTOS,
    DESCRIPTION_PREVIEW,
    FeedFilters,
    FeedItem,
)
from app.modules.jobs.application.responses import (
    GROUP_STATUSES,
    MyResponse,
    OwnerResponse,
    ResponseGroup,
    ResponseJob,
)
from app.modules.jobs.domain.alert import AlertId
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
from app.modules.jobs.domain.response import ACTIVE as ACTIVE_RESPONSES
from app.modules.jobs.domain.response import (
    Offer,
    ResponseId,
    ResponsePriceType,
    ResponseReview,
    ResponseStatus,
)
from app.modules.jobs.infrastructure.alerts import alert_fits
from app.modules.jobs.infrastructure.models import (
    AlertRow,
    HiddenJobRow,
    InviteRow,
    JobMediaRow,
    JobRow,
    ResponseRow,
    SavedJobRow,
)
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.db.types import GeoPointType
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId
from app.platform.kernel.pagination import Page, PageRequest

_J = JobRow.__table__.c
_M = JobMediaRow.__table__.c
_H = HiddenJobRow.__table__.c
_S = SavedJobRow.__table__.c
_R = ResponseRow.__table__.c
_I = InviteRow.__table__.c
_UNSEEN = (
    _R.deleted_at.is_(None),
    _R.review == ResponseReview.CLEAR.value,
    _R.status.in_([status.value for status in ACTIVE_RESPONSES]),
    or_(_J.responses_seen_at.is_(None), _R.updated_at > _J.responses_seen_at),
)
"""Новые для клиента: прошли проверку (или поправлены) после того, как он открыл отклики."""
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
_CARD = (
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
    _MEDIA_IDS,
)
"""Колонки карточки ленты S13 и сохранённых S12; расстояние добавляет запрос."""


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
        stmt = select(*_CARD, distance).where(*_feed_conditions(filters, viewer_id, now))
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

    async def job_of_response(self, response_id: ResponseId) -> JobId | None:
        row = await self._fetch_one(
            select(_R.job_id).where(_R.id == response_id, _R.deleted_at.is_(None))
        )
        return JobId(row["job_id"]) if row is not None else None

    async def performer_jobs(self, performer_id: UserId) -> list[JobId]:
        rows = await self._fetch(
            select(_R.job_id)
            .where(
                _R.performer_id == performer_id,
                _R.deleted_at.is_(None),
                _R.status.in_([status.value for status in ACTIVE_RESPONSES]),
            )
            .distinct()
        )
        return [JobId(row["job_id"]) for row in rows]

    async def count_active_responses(self, performer_id: UserId) -> int:
        row = await self._fetch_one(
            select(func.count().label("count")).where(
                _R.performer_id == performer_id,
                _R.deleted_at.is_(None),
                _R.status.in_([status.value for status in ACTIVE_RESPONSES]),
            )
        )
        return int(row["count"]) if row is not None else 0

    async def my_responses(
        self, performer_id: UserId, group: ResponseGroup | None, *, page: PageRequest
    ) -> Page[MyResponse]:
        stmt = (
            select(*_RESPONSE, _IS_FIRST, *_RESPONSE_JOB)
            .join_from(ResponseRow, JobRow, _J.id == _R.job_id)
            .where(_R.performer_id == performer_id, _R.deleted_at.is_(None))
        )
        if group is not None:
            stmt = stmt.where(_R.status.in_([status.value for status in GROUP_STATUSES[group]]))
        if page.cursor is not None:
            created_at, response_id = decode_cursor(page.cursor, (datetime, UUID))
            stmt = stmt.where(tuple_(_R.created_at, _R.id) < tuple_(created_at, response_id))
        rows = await self._fetch(
            stmt.order_by(_R.created_at.desc(), _R.id.desc()).limit(page.limit + 1)
        )
        items = [_my_response(row) for row in rows[: page.limit]]
        last = items[-1] if items else None
        more = len(rows) > page.limit
        cursor = encode_cursor(last.created_at, last.id) if more and last else None
        return Page(items=tuple(items), next_cursor=cursor)

    async def deal_response(self, response_id: ResponseId) -> DealResponse | None:
        row = await self._fetch_one(
            select(
                _R.id, _R.job_id, _R.performer_id, _R.status, _R.created_at, _R.availability_note
            ).where(_R.id == response_id, _R.deleted_at.is_(None))
        )
        if row is None:
            return None
        return DealResponse(
            id=ResponseId(row["id"]),
            job_id=JobId(row["job_id"]),
            performer_id=UserId(row["performer_id"]),
            status=ResponseStatus(row["status"]),
            created_at=row["created_at"],
            availability_note=row["availability_note"],
        )

    async def passed_over(self, job_id: JobId) -> list[UserId]:
        rows = await self._fetch(
            select(_R.performer_id).where(
                _R.job_id == job_id,
                _R.deleted_at.is_(None),
                _R.status == ResponseStatus.NOT_SELECTED.value,
            )
        )
        return [UserId(row["performer_id"]) for row in rows]

    async def closed_with(self, job_id: JobId) -> tuple[str, list[UserId]] | None:
        # удалённую заявку тоже: удаление открытой закрывает её отклики (Job.delete)
        job = await self._fetch_one(
            select(_J.title, _J.closed_at).where(
                _J.id == job_id, _J.status == JobStatus.CLOSED.value
            )
        )
        if job is None:
            return None
        # закрытие ставит откликам decided_at = closed_at: только они, без давно не выбранных
        rows = await self._fetch(
            select(_R.performer_id).where(
                _R.job_id == job_id,
                _R.deleted_at.is_(None),
                _R.status == ResponseStatus.NOT_SELECTED.value,
                _R.decided_at == job["closed_at"],
            )
        )
        return job["title"], [UserId(row["performer_id"]) for row in rows]

    async def is_invited(self, job_id: JobId, performer_id: UserId) -> bool:
        row = await self._fetch_one(
            select(_I.job_id).where(_I.job_id == job_id, _I.performer_id == performer_id).limit(1)
        )
        return row is not None

    async def performer_response(self, job_id: JobId, performer_id: UserId) -> MyResponseRef | None:
        row = await self._fetch_one(
            select(_R.id, _R.status, _R.review).where(
                _R.job_id == job_id, _R.performer_id == performer_id, _R.deleted_at.is_(None)
            )
        )
        if row is None:
            return None
        return MyResponseRef(
            id=ResponseId(row["id"]),
            status=ResponseStatus(row["status"]),
            review=ResponseReview(row["review"]),
        )

    async def my_response(self, performer_id: UserId, response_id: ResponseId) -> MyResponse | None:
        row = await self._fetch_one(
            select(*_RESPONSE, _IS_FIRST, *_RESPONSE_JOB)
            .join_from(ResponseRow, JobRow, _J.id == _R.job_id)
            .where(
                _R.id == response_id,
                _R.performer_id == performer_id,
                _R.deleted_at.is_(None),
            )
        )
        return _my_response(row) if row is not None else None

    async def owner_response(self, client_id: UserId, response_id: ResponseId) -> MyResponse | None:
        row = await self._fetch_one(
            select(*_RESPONSE, _IS_FIRST, *_RESPONSE_JOB)
            .join_from(ResponseRow, JobRow, _J.id == _R.job_id)
            .where(
                _R.id == response_id,
                _J.client_id == client_id,
                _R.review == ResponseReview.CLEAR.value,
                _R.deleted_at.is_(None),
                _J.deleted_at.is_(None),
            )
        )
        return _my_response(row) if row is not None else None

    async def my_response_counts(self, performer_id: UserId) -> dict[ResponseGroup, int]:
        rows = await self._fetch(
            select(_R.status, func.count().label("count"))
            .where(_R.performer_id == performer_id, _R.deleted_at.is_(None))
            .group_by(_R.status)
        )
        by_status = {ResponseStatus(row["status"]): int(row["count"]) for row in rows}
        return {
            group: sum(by_status.get(status, 0) for status in statuses)
            for group, statuses in GROUP_STATUSES.items()
        }

    async def unseen_responses(self, job_id: JobId) -> int:
        row = await self._fetch_one(
            select(func.count().label("count"))
            .select_from(ResponseRow)
            .join(JobRow, _J.id == _R.job_id)
            .where(_R.job_id == job_id, *_UNSEEN)
        )
        return int(row["count"]) if row is not None else 0

    async def unseen_total(self, client_id: UserId) -> int:
        row = await self._fetch_one(
            select(func.count().label("count"))
            .select_from(ResponseRow)
            .join(JobRow, _J.id == _R.job_id)
            .where(_J.client_id == client_id, _OPEN, *_UNSEEN)
        )
        return int(row["count"]) if row is not None else 0

    async def titles(self, job_ids: Collection[JobId]) -> dict[JobId, str]:
        if not job_ids:
            return {}
        rows = await self._fetch(
            select(_J.id, _J.title).where(_J.id.in_(list(job_ids)), _J.deleted_at.is_(None))
        )
        return {JobId(row["id"]): row["title"] for row in rows}

    async def unseen_counts(self, job_ids: Collection[JobId]) -> dict[JobId, int]:
        if not job_ids:
            return {}
        rows = await self._fetch(
            select(_R.job_id, func.count().label("count"))
            .select_from(ResponseRow)
            .join(JobRow, _J.id == _R.job_id)
            .where(_R.job_id.in_(list(job_ids)), *_UNSEEN)
            .group_by(_R.job_id)
        )
        return {JobId(row["job_id"]): int(row["count"]) for row in rows}

    async def job_responses(self, job_id: JobId) -> list[OwnerResponse]:
        rows = await self._fetch(
            select(*_RESPONSE, _IS_FIRST)
            .where(
                _R.job_id == job_id,
                _R.deleted_at.is_(None),
                _R.review == ResponseReview.CLEAR.value,
                _R.status != ResponseStatus.WITHDRAWN.value,
            )
            .order_by(_R.created_at, _R.id)
        )
        return [_owner_response(row) for row in rows]

    async def still_open(self, job_ids: Collection[JobId], now: datetime) -> set[JobId]:
        if not job_ids:
            return set()
        rows = await self._fetch(
            select(_J.id).where(
                _J.id.in_(list(job_ids)),
                _OPEN,
                or_(_J.expires_at.is_(None), _J.expires_at > now),
                _J.responses_count < _J.max_responses,
            )
        )
        return {JobId(row["id"]) for row in rows}

    async def skipped(self, job_ids: Collection[JobId], user_id: UserId) -> set[JobId]:
        if not job_ids:
            return set()
        wanted = list(job_ids)
        responded = select(_R.job_id.label("job_id")).where(
            _R.job_id.in_(wanted), _R.performer_id == user_id, _R.deleted_at.is_(None)
        )
        hidden = select(_H.job_id.label("job_id")).where(
            _H.job_id.in_(wanted), _H.user_id == user_id
        )
        rows = await self._fetch(responded.union(hidden))
        return {JobId(row["job_id"]) for row in rows}

    async def alert_counts(
        self, user_id: UserId, *, since: datetime, hidden_clients: Collection[UserId] = ()
    ) -> dict[AlertId, int]:
        alerts, jobs = AlertRow.__table__, JobRow.__table__
        matched = [
            *alert_fits(alerts, jobs),
            _J.published_at >= since,
            _J.visibility == Visibility.PUBLIC.value,
            _J.deleted_at.is_(None),
        ]
        if hidden_clients:
            matched.append(_J.client_id.not_in(list(hidden_clients)))
        # опубликованные за неделю — и те, что уже закрыты: подписке они подходили
        count = (
            select(func.count()).select_from(jobs).where(*matched).correlate(alerts)
        ).scalar_subquery()
        rows = await self._fetch(
            select(alerts.c.id, count.label("count")).where(alerts.c.user_id == user_id)
        )
        return {AlertId(row["id"]): int(row["count"]) for row in rows}

    async def saved(
        self, user_id: UserId, *, now: datetime, hidden_clients: Collection[UserId] = ()
    ) -> list[FeedItem]:
        stmt = (
            select(*_CARD, literal(None).label("distance"))
            .join_from(JobRow, SavedJobRow, and_(_S.job_id == _J.id, _S.user_id == user_id))
            .where(*_open_to_all(now))
        )
        if hidden_clients:
            stmt = stmt.where(_J.client_id.not_in(list(hidden_clients)))
        rows = await self._fetch(stmt.order_by(_S.created_at.desc(), _J.id.desc()))
        return [_feed_item(row) for row in rows]

    async def published_and_response(
        self, client_id: UserId, job_id: JobId, viewer_id: UserId | None
    ) -> tuple[int, MyResponseRef | None]:
        # частичный индекс ix_jobs_client_id_published (jobs_0009)
        published = (
            select(func.count())
            .where(_J.client_id == client_id, _J.published_at.is_not(None))
            .scalar_subquery()
            .label("published")
        )
        if viewer_id is None:
            [row] = await self._fetch(select(published))
            return int(row["published"]), None
        mine = (
            select(_R.id, _R.status, _R.review)
            .where(_R.job_id == job_id, _R.performer_id == viewer_id, _R.deleted_at.is_(None))
            .subquery("mine")
        )
        # строка счётчика есть всегда, отклик — если есть (LEFT JOIN к одной строке)
        one = select(literal(1).label("one")).subquery("one")
        [row] = await self._fetch(
            select(published, mine.c.id, mine.c.status, mine.c.review).select_from(
                one.outerjoin(mine, true())
            )
        )
        response = None
        if row["id"] is not None:
            response = MyResponseRef(
                id=ResponseId(row["id"]),
                status=ResponseStatus(row["status"]),
                review=ResponseReview(row["review"]),
            )
        return int(row["published"]), response

    async def count_active(self, client_id: UserId) -> int:
        row = await self._fetch_one(
            select(func.count().label("count")).where(
                _J.client_id == client_id,
                _J.deleted_at.is_(None),
                _J.status.in_([status.value for status in ACTIVE]),
            )
        )
        return int(row["count"]) if row is not None else 0


_EARLIER = ResponseRow.__table__.alias("earlier")
_IS_FIRST = (
    ~exists()
    .where(
        _EARLIER.c.job_id == _R.job_id,
        _EARLIER.c.deleted_at.is_(None),
        tuple_(_EARLIER.c.created_at, _EARLIER.c.id) < tuple_(_R.created_at, _R.id),
    )
    .correlate(ResponseRow)
).label("is_first")
"""Самый ранний неудалённый отклик заявки — «Откликнулся первым»."""
_RESPONSE = (
    _R.id,
    _R.performer_id,
    _R.profile_id,
    _R.status,
    _R.review,
    _R.revision,
    _R.message,
    _R.price_type,
    _R.price_amount,
    _R.availability_note,
    _R.created_at,
    _R.updated_at,
    _R.decided_at,
)
_RESPONSE_JOB = (
    _J.id.label("job_id"),
    _J.title,
    _J.status.label("job_status"),
    _J.category_id,
    _J.city_id,
    _J.district_id,
    _J.urgency,
    _J.preferred_from,
    _J.preferred_to,
    _J.budget_type,
    _J.budget_min,
    _J.budget_max,
    _J.budget_unit,
    _J.responses_count,
    _J.max_responses,
    _J.published_at,
)


def _offer(row: RowMapping) -> Offer:
    return Offer(
        message=row["message"],
        price_type=ResponsePriceType(row["price_type"]),
        price_amount=row["price_amount"],
        availability_note=row["availability_note"],
    )


def _my_response(row: RowMapping) -> MyResponse:
    district = row["district_id"]
    return MyResponse(
        id=ResponseId(row["id"]),
        performer_id=UserId(row["performer_id"]),
        status=ResponseStatus(row["status"]),
        review=ResponseReview(row["review"]),
        offer=_offer(row),
        revision=row["revision"],
        is_first=bool(row["is_first"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        decided_at=row["decided_at"],
        job=ResponseJob(
            id=JobId(row["job_id"]),
            title=row["title"],
            status=JobStatus(row["job_status"]),
            category_id=CategoryId(row["category_id"]),
            city_id=CityId(row["city_id"]),
            district_id=DistrictId(district) if district is not None else None,
            urgency=Urgency(row["urgency"]),
            preferred_from=row["preferred_from"],
            preferred_to=row["preferred_to"],
            budget_type=BudgetType(row["budget_type"]),
            budget_min=row["budget_min"],
            budget_max=row["budget_max"],
            budget_unit=BudgetUnit(row["budget_unit"]),
            responses_count=row["responses_count"],
            max_responses=row["max_responses"],
            published_at=row["published_at"],
        ),
    )


def _owner_response(row: RowMapping) -> OwnerResponse:
    return OwnerResponse(
        id=ResponseId(row["id"]),
        performer_id=UserId(row["performer_id"]),
        profile_id=row["profile_id"],
        status=ResponseStatus(row["status"]),
        offer=_offer(row),
        revision=row["revision"],
        is_first=bool(row["is_first"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _open_to_all(now: datetime) -> list[ColumnElement[bool]]:
    """Открыта для всех: опубликована, публична и срок не вышел."""
    return [
        _OPEN,
        _J.visibility == Visibility.PUBLIC.value,
        or_(_J.expires_at.is_(None), _J.expires_at > now),
    ]


def _feed_conditions(
    filters: FeedFilters, viewer_id: UserId | None, now: datetime
) -> list[ColumnElement[bool]]:
    conditions = [*_open_to_all(now)]
    if filters.city_id is not None:
        conditions.append(_J.city_id == filters.city_id)
    if filters.alerts_of is not None:
        alerts = AlertRow.__table__
        conditions.append(
            exists()
            .where(
                alerts.c.user_id == filters.alerts_of,
                alerts.c.is_active,
                *alert_fits(alerts, JobRow.__table__),
            )
            .correlate(JobRow)
        )
    if viewer_id is not None:
        conditions.append(_J.client_id != viewer_id)
        conditions.append(~exists().where(_H.user_id == viewer_id, _H.job_id == _J.id))
    if filters.hidden_clients:
        conditions.append(_J.client_id.not_in(list(filters.hidden_clients)))
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
        views_count=row["views_count"],
        notified_count=row["notified_count"],
        responses_seen_at=row["responses_seen_at"],
        moderation_note=row["moderation_note"],
        version=row["version"],
        created_at=row["created_at"],
        published_at=row["published_at"],
        expires_at=row["expires_at"],
        closed_at=row["closed_at"],
        close_reason=CloseReason(reason) if reason is not None else None,
    )
