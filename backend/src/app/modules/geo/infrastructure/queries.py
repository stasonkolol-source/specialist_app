"""Чтение справочника geo (ADR-0020 §5): города, районы, район точки."""

from collections.abc import Collection
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import ColumnElement, Float, and_, cast, func, literal, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.sql.expression import ColumnCollection

from app.modules.geo.api import DistrictSummary, ResolvedPoint
from app.modules.geo.application.dto import CityView, DistrictView, LocatedDistrict
from app.modules.geo.domain.place import CityStatus, DistrictKind
from app.modules.geo.infrastructure.models import CityRow, DistrictRow
from app.platform.cache.memo import Memo
from app.platform.db.query import SqlQuery
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId, DistrictId

MAX_NEAREST_KM = 15.0
"""Точка вне полигонов берёт ближайший центр района не дальше этого расстояния."""
NEAR_CITY_KM = 3.0
"""Район по точке (`locate`): точка не в квартале, но не дальше этого от города (окраина, дача за
границей района, погрешность GPS) — берётся ближайший квартал."""
SHAPE = Geography(geometry_type="GEOMETRY", srid=4326, spatial_index=False)


def _point(point: GeoPoint) -> Any:
    return func.ST_SetSRID(func.ST_MakePoint(point.lon, point.lat), 4326)


def _shape(columns: ColumnCollection[str, Any]) -> ColumnElement[Any]:
    """Район как geography — расстояния в метрах: граница, а без полигона — центр."""
    return func.coalesce(cast(columns.boundary, SHAPE), cast(columns.center, SHAPE))


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
            select(*_DISTRICT).where(d.city_id == city_id, d.is_active).order_by(d.kind, d.slug)
        )
        return [_district(row) for row in rows]

    async def all_districts(self) -> list[tuple[DistrictView, bool]]:
        """Все районы с признаком активности — для снимка справочника (без полигонов)."""
        d = DistrictRow.__table__.c
        rows = await self._fetch(select(*_DISTRICT, d.is_active).order_by(d.kind, d.slug))
        return [(_district(row), row["is_active"]) for row in rows]

    async def district(self, district_id: DistrictId) -> DistrictSummary | None:
        d = DistrictRow.__table__.c
        row = await self._fetch_one(
            select(d.id, d.city_id, d.slug, d.name, d.center).where(d.id == district_id)
        )
        return _summary(row) if row is not None else None

    async def district_summaries(
        self, district_ids: Collection[DistrictId]
    ) -> dict[DistrictId, DistrictSummary]:
        d = DistrictRow.__table__.c
        rows = await self._fetch(
            select(d.id, d.city_id, d.slug, d.name, d.center).where(d.id.in_(list(district_ids)))
        )
        return {summary.id: summary for summary in map(_summary, rows)}

    async def representations(self) -> Memo:
        return Memo()  # без снимка запоминать не в чем: строится на каждый запрос

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

    async def locate(self, city_id: CityId, point: GeoPoint) -> LocatedDistrict | None:
        """Квартал города под точкой — самый мелкий, если их несколько (на общей границе тоже).
        Иначе, если точка не дальше NEAR_CITY_KM от любого района города (муниципалитет-«весь
        город» тоже в счёт), — ближайший квартал. Только кварталы: их выбирают в списке районов
        (S20b, S32c), муниципалитет там не показывается."""
        d = DistrictRow.__table__.c
        here = _point(point)
        quarters = and_(
            d.city_id == city_id,
            d.is_active,
            d.kind == literal(DistrictKind.NEIGHBORHOOD.value),
        )
        covering = await self._fetch_one(
            select(*_DISTRICT)
            .where(quarters, func.ST_Covers(d.boundary, here))
            .order_by(func.ST_Area(d.boundary), d.id)
            .limit(1)
        )
        if covering is not None:
            return LocatedDistrict(district=_district(covering), exact=True)
        geography = cast(here, SHAPE)
        near = DistrictRow.__table__.alias("near")
        near_city = (
            select(near.c.id)
            .where(
                near.c.city_id == city_id,
                near.c.is_active,
                func.ST_DWithin(_shape(near.c), geography, NEAR_CITY_KM * 1000),
            )
            .exists()
        )
        nearest = await self._fetch_one(
            select(*_DISTRICT)
            .where(quarters, near_city)
            .order_by(func.ST_Distance(_shape(d), geography), d.id)
            .limit(1)
        )
        if nearest is None:
            return None
        return LocatedDistrict(district=_district(nearest), exact=False)


_D = DistrictRow.__table__.c
_DISTRICT = (_D.id, _D.city_id, _D.parent_id, _D.kind, _D.slug, _D.name, _D.center)


def _district(row: RowMapping) -> DistrictView:
    return DistrictView(
        id=DistrictId(row["id"]),
        city_id=CityId(row["city_id"]),
        parent_id=DistrictId(row["parent_id"]) if row["parent_id"] is not None else None,
        kind=DistrictKind(row["kind"]),
        slug=row["slug"],
        name=row["name"],
        center=row["center"],
    )


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
