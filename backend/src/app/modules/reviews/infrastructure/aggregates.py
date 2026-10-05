"""Рейтинг профилей в `reviews.rating_aggregates` (ARCHITECTURE §7.3) и данные для пересчёта:
опубликованные отзывы профиля и средние по категориям сделок."""

from collections.abc import Collection
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reviews.api import RatingSummary
from app.modules.reviews.domain.rating import CategoryStats, Rated, Rating
from app.modules.reviews.domain.review import ReviewKind, ReviewStatus
from app.modules.reviews.infrastructure.models import RatingAggregateRow, ReviewRow
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery

_RA = RatingAggregateRow.__table__.c
_R = ReviewRow.__table__.c
_AVG = Decimal("0.01")
_SCORE = Decimal("0.001")


def _published() -> list[Any]:
    """Отзывы, которые считает рейтинг: по сделкам, опубликованные, не стёртые."""
    return [
        _R.kind == ReviewKind.DEAL.value,
        _R.status == ReviewStatus.PUBLISHED.value,
        _R.deleted_at.is_(None),
    ]


class SqlRatingStore(SqlQuery):
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        super().__init__(session)
        self._uow = uow

    async def summaries(self, profile_ids: Collection[UUID]) -> dict[UUID, RatingSummary]:
        if not profile_ids:
            return {}
        rows = await self._fetch(
            select(
                _RA.subject_profile_id,
                _RA.rating_count,
                _RA.rating_bayes,
                _RA.rating_lower_bound,
                _RA.distribution,
                _RA.criteria_avg,
                _RA.last_published_at,
            ).where(_RA.subject_profile_id.in_(list(profile_ids)))
        )
        return {
            row["subject_profile_id"]: RatingSummary(
                count=row["rating_count"],
                average=float(row["rating_bayes"]),
                lower_bound=float(row["rating_lower_bound"]),
                distribution=tuple(row["distribution"]),
                criteria={name: float(value) for name, value in row["criteria_avg"].items()},
                last_published_at=row["last_published_at"],
            )
            for row in rows
        }

    async def lock(self, profile_id: UUID) -> None:
        self._uow.require_active()
        key = func.hashtextextended(f"reviews.rating:{profile_id}", 0)
        await self._session.execute(select(func.pg_advisory_xact_lock(key)))

    async def published_of(self, profile_id: UUID) -> list[Rated]:
        rows = await self._fetch(
            select(_R.rating, _R.criteria, _R.published_at, _R.category_id).where(
                _R.subject_profile_id == profile_id, *_published()
            )
        )
        return [
            Rated(
                rating=row["rating"],
                criteria={name: int(value) for name, value in row["criteria"].items()},
                published_at=row["published_at"],
                category_id=row["category_id"],
            )
            for row in rows
        ]

    async def category_stats(self) -> dict[int | None, CategoryStats]:
        rows = await self._fetch(
            select(
                _R.category_id,
                func.count().label("count"),
                func.sum(_R.rating).label("total"),
            )
            .where(*_published())
            .group_by(_R.category_id)
        )
        return {
            row["category_id"]: CategoryStats(count=row["count"], total=int(row["total"]))
            for row in rows
        }

    async def store(self, profile_id: UUID, rating: Rating | None) -> bool:
        self._uow.require_active()
        if rating is None:
            gone = await self._session.execute(
                delete(RatingAggregateRow)
                .where(RatingAggregateRow.subject_profile_id == profile_id)
                .returning(RatingAggregateRow.subject_profile_id)
            )
            return gone.scalar_one_or_none() is not None
        values = {
            "rating_count": rating.count,
            "rating_avg": Decimal(rating.average).quantize(_AVG, ROUND_HALF_UP),
            "rating_bayes": Decimal(rating.bayes).quantize(_SCORE, ROUND_HALF_UP),
            "rating_lower_bound": Decimal(rating.lower_bound).quantize(_SCORE, ROUND_HALF_UP),
            "distribution": list(rating.distribution),
            "criteria_avg": {name: round(value, 2) for name, value in rating.criteria.items()},
            "last_published_at": rating.last_published_at,
        }
        before = await self._session.execute(
            select(*(_RA[name] for name in values)).where(_RA.subject_profile_id == profile_id)
        )
        old = before.mappings().one_or_none()
        if old is not None and _same(dict(old), values):
            return False
        stmt = insert(RatingAggregateRow).values(subject_profile_id=profile_id, **values)
        await self._session.execute(
            stmt.on_conflict_do_update(
                index_elements=["subject_profile_id"],
                set_={**values, "updated_at": func.now()},
            )
        )
        return True

    async def rated_profiles(self) -> list[UUID]:
        # и профили с опубликованными отзывами без строки рейтинга: отзывы, привязанные к профилю
        # миграцией reviews_0005 (UXM-12), ночной пересчёт подхватит сам
        rows = await self._fetch(
            select(_RA.subject_profile_id).union(
                select(_R.subject_profile_id).where(
                    _R.subject_profile_id.is_not(None), *_published()
                )
            )
        )
        return [row["subject_profile_id"] for row in rows]


def _same(old: dict[str, Any], new: dict[str, Any]) -> bool:
    """Записанное совпадает с новым: пересчёт ничего не изменил (событие не нужно)."""
    return all(
        (float(old[name]) == float(value)) if isinstance(value, Decimal) else old[name] == value
        for name, value in new.items()
    )
