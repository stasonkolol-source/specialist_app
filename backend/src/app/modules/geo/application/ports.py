"""Порты модуля geo (ADR-0020 §3, §5). Справочник: запись только импортом сидов и админкой."""

from collections.abc import Collection
from typing import Protocol

from app.modules.geo.api import DistrictSummary, ResolvedPoint
from app.modules.geo.application.dto import (
    CitySeed,
    CityView,
    DistrictView,
    ImportResult,
    LocatedDistrict,
)
from app.platform.cache.memo import Memo
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId, DistrictId


class GeoQuery(Protocol):
    async def cities(self) -> list[CityView]: ...

    async def city(self, city_id: CityId) -> CityView | None: ...

    async def districts(self, city_id: CityId) -> list[DistrictView]: ...

    async def district(self, district_id: DistrictId) -> DistrictSummary | None: ...

    async def district_summaries(
        self, district_ids: Collection[DistrictId]
    ) -> dict[DistrictId, DistrictSummary]:
        """Районы пачкой (любые, как `district`); кого нет — нет и в ответе."""
        ...

    async def resolve(self, point: GeoPoint) -> ResolvedPoint | None: ...

    async def locate(self, city_id: CityId, point: GeoPoint) -> LocatedDistrict | None:
        """Район города для выбора (квартал) под точкой; у края города — ближайший; дальше —
        None."""
        ...

    async def representations(self) -> Memo:
        """Ответы справочника (тело и ETag) текущего снимка: строятся раз на снимок."""
        ...


class DirectoryCache(Protocol):
    """Снимок справочника в памяти процесса: импорт в этом процессе сбрасывает его сразу,
    в остальных он обновится за TTL."""

    def invalidate(self) -> None: ...


class GeoWriter(Protocol):
    async def upsert_city(self, seed: CitySeed) -> ImportResult:
        """Идемпотентно: неизменённые город и районы не трогаются."""
        ...
