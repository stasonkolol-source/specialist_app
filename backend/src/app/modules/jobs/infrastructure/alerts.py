"""Подписки на заявки и их совпадения в PostgreSQL (DEVELOPMENT_PLAN 5.7; ARCHITECTURE §9.6).

`alert_fits` — правило §9.6 «заявка подходит подписке» одним выражением: им пользуются матчинг
новой заявки, лента «по моим подпискам» и счётчик «N заявок за неделю» S18 — у всех трёх один
ответ. Отличия от SQL §9.6:
- круг — `ST_DWithin` по центру подписки с константным потолком 30 км (GiST по `center`
  участвует в плане), а не полигон `area` (миграция jobs_0010);
- заявка без языка подходит любой подписке (как в ленте 5.3), договорная — подписке с бюджетом
  «от» (как в §9.6: о цене договорятся в отклике).
Правку подписок пользователя сериализует advisory lock транзакции, как у шаблонов откликов.
"""

from collections.abc import Collection
from datetime import datetime, timedelta

from sqlalchemy import (
    ColumnElement,
    FromClause,
    and_,
    any_,
    delete,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.application.alerts import (
    AlertCandidate,
    AlertMatch,
    PendingDigest,
    RecentCards,
)
from app.modules.jobs.domain.alert import (
    MAX_RADIUS_M,
    AlertCriteria,
    AlertDelivery,
    AlertId,
    JobAlert,
)
from app.modules.jobs.domain.job import BudgetType, JobId, Urgency
from app.modules.jobs.infrastructure.models import AlertMatchRow, AlertRow, JobRow
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId

_A = AlertRow.__table__.c
_AM = AlertMatchRow.__table__.c
_J = JobRow.__table__.c


def alert_fits(alerts: FromClause, jobs: FromClause) -> list[ColumnElement[bool]]:
    """Заявка `jobs` подходит подписке `alerts` (§9.6): без «включена» и паузы — их добавляет
    тот, кому они нужны."""
    a, j = alerts.c, jobs.c
    return [
        a.category_ids.overlap(j.category_path),
        a.city_id == j.city_id,
        or_(
            and_(func.cardinality(a.district_ids) == 0, a.center.is_(None)),
            j.district_id == any_(a.district_ids),
            and_(
                func.ST_DWithin(a.center, j.point_public, MAX_RADIUS_M),
                func.ST_DWithin(a.center, j.point_public, a.radius_m),
            ),
        ),
        or_(
            a.min_budget.is_(None),
            j.budget_type == BudgetType.NEGOTIABLE.value,
            func.coalesce(j.budget_max, j.budget_min) >= a.min_budget,
        ),
        or_(func.cardinality(a.urgencies) == 0, j.urgency == any_(a.urgencies)),
        or_(
            func.cardinality(a.languages) == 0,
            func.cardinality(j.languages) == 0,
            a.languages.overlap(j.languages),
        ),
        a.user_id != j.client_id,
    ]


def receiving(now: datetime) -> list[ColumnElement[bool]]:
    """Подписка присылает заявки: включена и не на паузе."""
    return [_A.is_active, or_(_A.paused_until.is_(None), _A.paused_until <= now)]


class SqlJobAlerts:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def lock(self, user_id: UserId) -> None:
        self._uow.require_active()
        key = func.hashtextextended(f"jobs.alerts:{user_id}", 0)
        await self._session.execute(select(func.pg_advisory_xact_lock(key)))

    async def of_user(self, user_id: UserId) -> list[JobAlert]:
        rows = (
            await self._session.execute(
                select(AlertRow)
                .where(_A.user_id == user_id)
                .order_by(_A.created_at, _A.id)
                .execution_options(populate_existing=True)
            )
        ).scalars()
        return [_alert(row) for row in rows]

    async def get(self, alert_id: AlertId) -> JobAlert | None:
        row = (
            await self._session.execute(
                select(AlertRow).where(_A.id == alert_id).execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return _alert(row) if row is not None else None

    async def add(self, alert: JobAlert) -> None:
        self._uow.require_active()
        row = AlertRow(id=alert.id, user_id=alert.user_id, created_at=alert.created_at)
        _apply(alert, row)
        self._session.add(row)
        await self._session.flush()

    async def save(self, alert: JobAlert) -> None:
        self._uow.require_active()
        row = await self._session.get(AlertRow, alert.id)
        if row is not None:
            _apply(alert, row)
            await self._session.flush()

    async def delete(self, alert_id: AlertId) -> None:
        self._uow.require_active()
        # совпадения подписки — каскадом (FK ON DELETE CASCADE)
        await self._session.execute(
            delete(AlertRow).where(_A.id == alert_id).execution_options(synchronize_session=False)
        )

    async def forget(self, user_id: UserId) -> None:
        self._uow.require_active()
        await self._session.execute(delete(AlertMatchRow).where(_AM.user_id == user_id))
        await self._session.execute(
            delete(AlertRow)
            .where(_A.user_id == user_id)
            .execution_options(synchronize_session=False)
        )


class SqlAlertMatches:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def candidates(self, job_id: JobId, now: datetime) -> list[AlertCandidate]:
        alerts, jobs = AlertRow.__table__, JobRow.__table__
        distance = func.ST_Distance(_A.center, _J.point_public).label("distance")
        rows = (
            await self._session.execute(
                select(_A.id, _A.user_id, _A.delivery, distance)
                .select_from(alerts)
                .join(jobs, _J.id == job_id)
                .where(*receiving(now), *alert_fits(alerts, jobs))
                .order_by(_A.created_at, _A.id)
            )
        ).mappings()
        return [
            AlertCandidate(
                alert_id=AlertId(row["id"]),
                user_id=UserId(row["user_id"]),
                delivery=AlertDelivery(row["delivery"]),
                distance_m=row["distance"],
            )
            for row in rows
        ]

    async def recent_cards(
        self, user_ids: Collection[UserId], now: datetime
    ) -> dict[UserId, RecentCards]:
        if not user_ids:
            return {}
        hour = now - timedelta(hours=1)
        rows = (
            await self._session.execute(
                select(
                    _AM.user_id,
                    func.count().filter(_AM.created_at > hour).label("hour"),
                    func.count().label("day"),
                )
                .where(
                    _AM.user_id.in_(list(user_ids)),
                    _AM.created_at > now - timedelta(days=1),
                    _AM.delivery == AlertDelivery.INSTANT.value,
                )
                .group_by(_AM.user_id)
            )
        ).mappings()
        return {
            UserId(row["user_id"]): RecentCards(hour=int(row["hour"]), day=int(row["day"]))
            for row in rows
        }

    async def record(
        self, job_id: JobId, matches: Collection[AlertMatch], now: datetime
    ) -> list[AlertMatch]:
        self._uow.require_active()
        if not matches:
            return []
        stmt = (
            insert(AlertMatchRow)
            .values(
                [
                    {
                        "job_id": job_id,
                        "user_id": match.user_id,
                        "alert_id": match.alert_id,
                        "delivery": match.delivery,
                        "created_at": now,
                    }
                    for match in matches
                ]
            )
            .on_conflict_do_nothing(index_elements=["job_id", "user_id"])
            .returning(_AM.user_id)
        )
        added = {UserId(user_id) for user_id in (await self._session.scalars(stmt)).all()}
        return [match for match in matches if match.user_id in added]

    async def add_notified(self, job_id: JobId, count: int) -> None:
        self._uow.require_active()
        await self._session.execute(
            update(JobRow)
            .where(_J.id == job_id)
            # updated_at — как было: подсчёт подписчиков не правка заявки
            .values(notified_count=_J.notified_count + count, updated_at=_J.updated_at)
            .execution_options(synchronize_session=False)
        )

    async def pending_digests(self, *, limit: int) -> list[PendingDigest]:
        rows = (
            await self._session.execute(
                select(_AM.user_id, _AM.alert_id, _AM.job_id)
                .where(
                    _AM.delivery == AlertDelivery.DIGEST.value,
                    _AM.digested_at.is_(None),
                )
                .order_by(_AM.created_at)
                .limit(limit)
            )
        ).mappings()
        return [
            PendingDigest(
                user_id=UserId(row["user_id"]),
                alert_id=AlertId(row["alert_id"]),
                job_id=JobId(row["job_id"]),
            )
            for row in rows
        ]

    async def mark_digested(self, user_ids: Collection[UserId], at: datetime) -> None:
        self._uow.require_active()
        if not user_ids:
            return
        await self._session.execute(
            update(AlertMatchRow)
            .where(
                _AM.user_id.in_(list(user_ids)),
                _AM.delivery == AlertDelivery.DIGEST.value,
                _AM.digested_at.is_(None),
                _AM.created_at <= at,
            )
            .values(digested_at=at)
            .execution_options(synchronize_session=False)
        )

    async def purge(self, before: datetime) -> int:
        self._uow.require_active()
        result = await self._session.execute(
            delete(AlertMatchRow)
            .where(_AM.created_at < before)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # CursorResult у DML


def _alert(row: AlertRow) -> JobAlert:
    return JobAlert(
        id=AlertId(row.id),
        user_id=UserId(row.user_id),
        criteria=AlertCriteria(
            category_ids=tuple(CategoryId(item) for item in row.category_ids),
            city_id=CityId(row.city_id),
            district_ids=tuple(DistrictId(item) for item in row.district_ids),
            center=row.center,
            radius_m=row.radius_m,
            min_budget=row.min_budget,
            urgencies=tuple(Urgency(item) for item in row.urgencies),
            languages=tuple(row.languages),
        ),
        delivery=row.delivery,
        is_active=row.is_active,
        paused_until=row.paused_until,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _apply(alert: JobAlert, row: AlertRow) -> None:
    criteria = alert.criteria
    row.category_ids = list(criteria.category_ids)
    row.city_id = criteria.city_id
    row.district_ids = list(criteria.district_ids)
    row.center = criteria.center
    row.radius_m = criteria.radius_m
    row.min_budget = criteria.min_budget
    row.urgencies = [urgency.value for urgency in criteria.urgencies]
    row.languages = list(criteria.languages)
    row.delivery = alert.delivery
    row.is_active = alert.is_active
    row.paused_until = alert.paused_until
    row.updated_at = alert.updated_at
