"""Агрегаты рейтинга из `reviews.rating_aggregates` (ARCHITECTURE §7.3)."""

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select

from app.modules.reviews.api import RatingSummary
from app.modules.reviews.infrastructure.models import RatingAggregateRow
from app.platform.db.query import SqlQuery

_RA = RatingAggregateRow.__table__.c


class SqlRatingAggregates(SqlQuery):
    async def summaries(self, profile_ids: Collection[UUID]) -> dict[UUID, RatingSummary]:
        if not profile_ids:
            return {}
        rows = await self._fetch(
            select(
                _RA.subject_profile_id,
                _RA.rating_count,
                _RA.rating_avg,
                _RA.distribution,
                _RA.criteria_avg,
            ).where(_RA.subject_profile_id.in_(list(profile_ids)))
        )
        return {
            row["subject_profile_id"]: RatingSummary(
                count=row["rating_count"],
                average=float(row["rating_avg"]),
                distribution=tuple(row["distribution"]),
                criteria={name: float(value) for name, value in row["criteria_avg"].items()},
            )
            for row in rows
        }
