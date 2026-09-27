"""Чтение справочника geo (ADR-0020 §5): города, районы, район точки."""

from typing import Any

from sqlalchemy import Float, and_, cast, func, literal, select
from sqlalchemy.engine import RowMapping

from app.modules.geo.api import DistrictSummary, ResolvedPoint
from app.modules.geo.application.dto import CityView, DistrictView
from app.modules.geo.domain.place import CityStatus, DistrictKind
from app.modules.geo.infrastructure.models import CityRow, DistrictRow
from app.platform.db.query import SqlQuery
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId, DistrictId

MAX_NEAREST_KM = 15.0
"""Точка вне полигонов берёт ближайший центр района не дальше этого расстояния."""


def _point(point: GeoPoint) -> Any:
    return func.ST_SetSRID(func.ST_MakePoint(point.lon, point.lat), 4326)


class SqlGeoQuery(SqlQuery):
    async def cities(self) -> list[CityView]:
        c = CityRow.__table__.c
        rows = await self._fetch(
            select(c.id, c.slug, c.name, c.center, c.is_active).order_by(c.sort_order, c.slug)
        )
        return [_city(row) for row in rows]

    async def city(self, city_id: CityId) -> CityView | None:
        c = CityRow.__table__.c
        row = await self._fetch_one(
            select(c.id, c.slug, c.name, c.center, c.is_active).where(c.id == city_id)
        )
        return _city(row) if row is not None else None

    async def districts(self, city_id: CityId) -> list[DistrictView]:
        d = DistrictRow.__table__.c
        rows = await self._fetch(
            select(d.id, d.city_id, d.parent_id, d.kind, d.slug, d.name, d.center)
            .where(d.city_id == city_id, d.is_active)
            .order_by(d.kind, d.slug)
        )
        return [
            DistrictView(
                id=DistrictId(row["id"]),
                city_id=CityId(row["city_id"]),
                parent_id=DistrictId(row["parent_id"]) if row["parent_id"] is not None else None,
                kind=DistrictKind(row["kind"]),
                slug=row["slug"],
                name=row["name"],
                center=row["center"],
            )
            for row in rows
        ]

    async def district(self, district_id: DistrictId) -> DistrictSummary | None:
        d = DistrictRow.__table__.c
        row = await self._fetch_one(
            select(d.id, d.city_id, d.slug, d.name, d.center).where(d.id == district_id)
        )
        return _summary(row) if row is not None else None

    async def resolve(self, point: GeoPoint) -> ResolvedPoint | None:
        """Самый мелкий полигон активного города, иначе ближайший центр (ARCHITECTURE §7.6)."""
        d, c = DistrictRow.__table__.c, CityRow.__table__.c
        active = and_(d.is_active, c.is_active)
        covering = await self._fetch_one(
            select(d.id, d.city_id, d.slug, d.name, d.center)
            .join(CityRow.__table__, c.id == d.city_id)
            .where(active, func.ST_Covers(d.boundary, _point(point)))
            .order_by(
                (d.kind == literal(DistrictKind.NEIGHBORHOOD.value)).desc(),
                func.ST_Area(d.boundary),
            )
            .limit(1)
        )
        if covering is not None:
            return ResolvedPoint(district=_summary(covering), exact=True)
        geography = cast(_point(point), d.center.type)
        nearest = await self._fetch_one(
            select(
                d.id,
                d.city_id,
                d.slug,
                d.name,
                d.center,
                cast(func.ST_Distance(d.center, geography), Float).label("meters"),
            )
            .join(CityRow.__table__, c.id == d.city_id)
            .where(active, func.ST_DWithin(d.center, geography, MAX_NEAREST_KM * 1000))
            .order_by(d.center.op("<->")(geography))
            .limit(1)
        )
        if nearest is None:
            return None
        return ResolvedPoint(district=_summary(nearest), exact=False)


def _city(row: RowMapping) -> CityView:
    return CityView(
        id=CityId(row["id"]),
        slug=row["slug"],
        name=row["name"],
        center=row["center"],
        status=CityStatus.ACTIVE if row["is_active"] else CityStatus.SOON,
    )


def _summary(row: RowMapping) -> DistrictSummary:
    return DistrictSummary(
        id=DistrictId(row["id"]),
        city_id=CityId(row["city_id"]),
        slug=row["slug"],
        name=row["name"],
        center=row["center"],
    )
