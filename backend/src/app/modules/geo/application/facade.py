"""Реализация GeoApi для identity, specialists и jobs (ADR-0020 §6)."""

from app.modules.geo.api import DistrictSummary, GeoApi, ResolvedPoint
from app.modules.geo.application.ports import GeoQuery
from app.modules.geo.domain.privacy import blur
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import DistrictId


class GeoFacade(GeoApi):
    def __init__(self, query: GeoQuery) -> None:
        self._query = query

    async def resolve(self, point: GeoPoint) -> ResolvedPoint | None:
        return await self._query.resolve(point)

    async def district(self, district_id: DistrictId) -> DistrictSummary | None:
        return await self._query.district(district_id)

    def public_point(self, point: GeoPoint, *, seed: bytes) -> GeoPoint:
        return blur(point, seed=seed)
