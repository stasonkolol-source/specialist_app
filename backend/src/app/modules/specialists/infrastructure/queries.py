"""Запросы specialists (ADR-0020 §4): свой профиль для кабинета и профили для поиска (4.1)."""

from collections import defaultdict
from collections.abc import Collection
from uuid import UUID

from sqlalchemy import RowMapping, Select, select

from app.modules.specialists.api import ProfileForIndex, ProfileRef, PublicProfile, PublicWork
from app.modules.specialists.application.dto import ProfileView
from app.modules.specialists.domain.portfolio import WorkStatus
from app.modules.specialists.domain.profile import (
    Language,
    ProfileId,
    ProfileStatus,
    WorkMode,
    missing_fields,
)
from app.modules.specialists.infrastructure.models import (
    PortfolioItemRow,
    PortfolioMediaRow,
    ProfileCategoryRow,
    ProfileRow,
    ServiceAreaRow,
)
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, MediaId, UserId


class SqlProfileQuery(SqlQuery):
    async def refs_of_users(self, user_ids: Collection[UserId]) -> dict[UserId, ProfileRef]:
        if not user_ids:
            return {}
        p = ProfileRow.__table__.c
        rows = await self._fetch(
            select(p.id, p.user_id, p.kind, p.status, p.display_name).where(
                p.user_id.in_(list(user_ids)), p.deleted_at.is_(None)
            )
        )
        return {
            UserId(row["user_id"]): ProfileRef(
                id=row["id"],
                kind=str(row["kind"]),
                status=str(row["status"]),
                display_name=row["display_name"],
            )
            for row in rows
        }

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

    async def for_index(self, profile_ids: Collection[UUID]) -> list[ProfileForIndex]:
        """Неудалённые профили с категориями и районами — тремя запросами на пачку."""
        ids = list(profile_ids)
        if not ids:
            return []
        c, a = ProfileCategoryRow.__table__.c, ServiceAreaRow.__table__.c
        rows = await self._fetch(
            select(ProfileRow.__table__).where(
                ProfileRow.id.in_(ids), ProfileRow.deleted_at.is_(None)
            )
        )
        categories = await self._grouped(
            select(c.profile_id, c.category_id.label("item"))
            .where(c.profile_id.in_(ids))
            .order_by(c.profile_id, c.position)
        )
        areas = await self._grouped(
            select(a.profile_id, a.district_id.label("item"))
            .where(a.profile_id.in_(ids))
            .order_by(a.profile_id, a.position)
        )
        return [
            _for_index(row, categories.get(row["id"], ()), areas.get(row["id"], ())) for row in rows
        ]

    async def public(self, profile_id: UUID) -> PublicProfile | None:
        """Опубликованный профиль, его категории, районы и работы — четырьмя запросами."""
        p = ProfileRow.__table__.c
        row = await self._fetch_one(
            select(ProfileRow.__table__).where(
                p.id == profile_id, p.status == ProfileStatus.PUBLISHED, p.deleted_at.is_(None)
            )
        )
        if row is None:
            return None
        c, a = ProfileCategoryRow.__table__.c, ServiceAreaRow.__table__.c
        categories = await self._grouped(
            select(c.profile_id, c.category_id.label("item"))
            .where(c.profile_id == profile_id)
            .order_by(c.position)
        )
        areas = await self._grouped(
            select(a.profile_id, a.district_id.label("item"))
            .where(a.profile_id == profile_id)
            .order_by(a.position)
        )
        w, m = PortfolioItemRow.__table__.c, PortfolioMediaRow.__table__.c
        works = await self._fetch(
            select(w.id, w.title, m.media_id, m.kind)
            .join(PortfolioMediaRow.__table__, m.item_id == w.id)
            .where(
                w.profile_id == profile_id,
                w.deleted_at.is_(None),
                w.status == WorkStatus.PUBLISHED,
            )
            .order_by(w.position, w.created_at, m.position)
        )
        return _public(
            row,
            categories.get(profile_id, ()),
            areas.get(profile_id, ()),
            tuple(
                PublicWork(
                    id=work["id"],
                    kind=work["kind"].value,
                    caption=work["title"],
                    media_id=MediaId(work["media_id"]),
                )
                for work in works
            ),
        )

    async def published_ids(self, *, after: UUID | None, limit: int) -> list[UUID]:
        p = ProfileRow.__table__.c
        stmt = (
            select(p.id)
            .where(p.status == ProfileStatus.PUBLISHED, p.deleted_at.is_(None))
            .order_by(p.id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(p.id > after)
        return [row["id"] for row in await self._fetch(stmt)]

    async def _grouped(self, stmt: Select[tuple[UUID, int]]) -> dict[UUID, tuple[int, ...]]:
        grouped: defaultdict[UUID, list[int]] = defaultdict(list)
        for row in await self._fetch(stmt):
            grouped[row["profile_id"]].append(row["item"])
        return {profile_id: tuple(items) for profile_id, items in grouped.items()}


def _for_index(
    row: RowMapping, category_ids: tuple[int, ...], area_ids: tuple[int, ...]
) -> ProfileForIndex:
    return ProfileForIndex(
        id=row["id"],
        user_id=UserId(row["user_id"]),
        kind=row["kind"].value,
        status=row["status"].value,
        listed_in_catalog=row["listed_in_catalog"],
        display_name=row["display_name"],
        headline=row["headline"],
        about=row["about"],
        languages=tuple(row["languages"]),
        city_id=CityId(row["city_id"]),
        area_ids=tuple(DistrictId(item) for item in area_ids),
        base_point=row["base_point"],
        base_point_public=row["base_point_public"],
        travel_radius_km=row["travel_radius_km"],
        work_modes=tuple(row["work_modes"]),
        category_ids=tuple(CategoryId(item) for item in category_ids),
        available_until=row["available_until"],
        avatar_media_id=MediaId(row["avatar_media_id"]) if row["avatar_media_id"] else None,
        published_at=row["published_at"],
        updated_at=row["updated_at"],
    )


def _public(
    row: RowMapping,
    category_ids: tuple[int, ...],
    area_ids: tuple[int, ...],
    works: tuple[PublicWork, ...],
) -> PublicProfile:
    return PublicProfile(
        id=row["id"],
        user_id=UserId(row["user_id"]),
        kind=row["kind"].value,
        display_name=row["display_name"],
        headline=row["headline"],
        about=row["about"],
        languages=tuple(row["languages"]),
        city_id=CityId(row["city_id"]),
        area_ids=tuple(DistrictId(item) for item in area_ids),
        travel_radius_km=row["travel_radius_km"],
        work_modes=tuple(row["work_modes"]),
        category_ids=tuple(CategoryId(item) for item in category_ids),
        available_until=row["available_until"],
        avatar_media_id=MediaId(row["avatar_media_id"]) if row["avatar_media_id"] else None,
        is_founding=row["is_founding"],
        published_at=row["published_at"],
        works=works,
    )
