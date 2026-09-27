"""Фейки фасадов других модулей для тестов identity (ADR-0020 §11)."""

from dataclasses import dataclass, field

from app.modules.geo.api import CitySummary, DistrictSummary, ResolvedPoint
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId, DistrictId
from app.platform.kernel.localized import Locale, LocalizedText


def a_city(city_id: int, *, active: bool = True, slug: str = "novi-sad") -> CitySummary:
    return CitySummary(
        id=CityId(city_id),
        slug=slug,
        name=LocalizedText({Locale.RU: "Нови-Сад", Locale.SR_CYRL: "Нови Сад"}),
        is_active=active,
    )


@dataclass
class FakeGeo:
    """GeoApi: справочник городов задаёт тест; районы и точки identity не нужны."""

    cities: dict[CityId, CitySummary] = field(default_factory=dict)

    def add(self, city: CitySummary) -> CitySummary:
        self.cities[city.id] = city
        return city

    async def city(self, city_id: CityId) -> CitySummary | None:
        return self.cities.get(city_id)

    async def resolve(self, point: GeoPoint) -> ResolvedPoint | None:
        return None

    async def district(self, district_id: DistrictId) -> DistrictSummary | None:
        return None

    def public_point(self, point: GeoPoint, *, seed: bytes) -> GeoPoint:
        return point
