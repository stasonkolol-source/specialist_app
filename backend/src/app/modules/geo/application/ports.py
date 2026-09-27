"""Порты модуля geo (ADR-0020 §3, §5). Справочник: запись только импортом сидов и админкой."""

from typing import Protocol

from app.modules.geo.api import DistrictSummary, ResolvedPoint
from app.modules.geo.application.dto import CitySeed, CityView, DistrictView, ImportResult
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId, DistrictId


class GeoQuery(Protocol):
    async def cities(self) -> list[CityView]: ...

    async def city(self, city_id: CityId) -> CityView | None: ...

    async def districts(self, city_id: CityId) -> list[DistrictView]: ...

    async def district(self, district_id: DistrictId) -> DistrictSummary | None: ...

    async def resolve(self, point: GeoPoint) -> ResolvedPoint | None: ...


class GeoWriter(Protocol):
    async def upsert_city(self, seed: CitySeed) -> ImportResult:
        """Идемпотентно: неизменённые город и районы не трогаются."""
        ...
