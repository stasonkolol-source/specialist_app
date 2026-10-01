"""Запросы specialists (ADR-0020 §4): свой профиль для кабинета."""

from sqlalchemy import select

from app.modules.specialists.application.dto import ProfileView
from app.modules.specialists.domain.profile import Language, ProfileId, WorkMode, missing_fields
from app.modules.specialists.infrastructure.models import (
    ProfileCategoryRow,
    ProfileRow,
    ServiceAreaRow,
)
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId


class SqlProfileQuery(SqlQuery):
    async def of_user(self, user_id: UserId) -> ProfileView | None:
        p = ProfileRow.__table__.c
        row = await self._fetch_one(
            select(ProfileRow.__table__).where(p.user_id == user_id, p.deleted_at.is_(None))
        )
        if row is None:
            return None
        c, a = ProfileCategoryRow.__table__.c, ServiceAreaRow.__table__.c
        category_ids = tuple(
            CategoryId(r["category_id"])
            for r in await self._fetch(
                select(c.category_id).where(c.profile_id == row["id"]).order_by(c.position)
            )
        )
        area_ids = tuple(
            DistrictId(r["district_id"])
            for r in await self._fetch(
                select(a.district_id).where(a.profile_id == row["id"]).order_by(a.position)
            )
        )
        work_modes = tuple(WorkMode(v) for v in row["work_modes"])
        return ProfileView(
            id=ProfileId(row["id"]),
            kind=row["kind"],
            status=row["status"],
            display_name=row["display_name"],
            headline=row["headline"],
            about=row["about"],
            languages=tuple(Language(v) for v in row["languages"]),
            city_id=CityId(row["city_id"]),
            category_ids=category_ids,
            area_ids=area_ids,
            travel_radius_km=row["travel_radius_km"],
            work_modes=work_modes,
            listed_in_catalog=row["listed_in_catalog"],
            rejection_reason=row["rejection_reason"],
            missing=missing_fields(
                category_ids=category_ids,
                headline=row["headline"],
                work_modes=work_modes,
                area_ids=area_ids,
            ),
            available_until=row["available_until"],
            avatar_media_id=MediaId(row["avatar_media_id"]) if row["avatar_media_id"] else None,
            published_at=row["published_at"],
            version=row["version"],
        )
