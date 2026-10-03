"""Реализация GeoApi для identity, specialists и jobs (ADR-0020 §6)."""

from collections.abc import Collection

from app.modules.geo.api import CitySummary, DistrictSummary, GeoApi, ResolvedPoint
from app.modules.geo.application.ports import GeoQuery
from app.modules.geo.domain.place import CityStatus
from app.modules.geo.domain.privacy import blur
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId, DistrictId


class GeoFacade(GeoApi):
    def __init__(self, query: GeoQuery) -> None:
        self._query = query

    async def city(self, city_id: CityId) -> CitySummary | None:
        city = await self._query.city(city_id)
        if city is None:
            return None
        return CitySummary(
            id=city.id,
            slug=city.slug,
            name=city.name,
            is_active=city.status is CityStatus.ACTIVE,
        )

    async def resolve(self, point: GeoPoint) -> ResolvedPoint | None:
        return await self._query.resolve(point)

    async def district(self, district_id: DistrictId) -> DistrictSummary | None:
        return await self._query.district(district_id)

    async def districts(
        self, district_ids: Collection[DistrictId]
    ) -> dict[DistrictId, DistrictSummary]:
        return await self._query.district_summaries(district_ids) if district_ids else {}

    def public_point(self, point: GeoPoint, *, seed: bytes) -> GeoPoint:
        return blur(point, seed=seed)
