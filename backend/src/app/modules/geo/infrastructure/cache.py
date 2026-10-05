"""Справочник geo в памяти процесса (перф-аудит 2026-10): города и районы без полигонов.

Города и районы читает почти каждый экран — список городов, районы S08, карточки откликов
S23, место в сделке S26, — а меняет их только импорт сидов. Снимок целиком (два запроса)
живёт минуту (platform/cache/snapshot.py); район точки (PostGIS) — по-прежнему запросом.
Чего нет в снимке (город или район добавлен после него), читается из базы: новое видно сразу.
"""

from collections.abc import Collection, Sequence
from datetime import timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.geo.api import DistrictSummary, ResolvedPoint
from app.modules.geo.application.dto import CityView, DistrictView, LocatedDistrict
from app.modules.geo.application.ports import GeoQuery
from app.modules.geo.infrastructure.queries import SqlGeoQuery
from app.platform.cache.memo import Memo
from app.platform.cache.snapshot import SnapshotCache
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId, DistrictId

TTL: Final = timedelta(seconds=60)
"""Как у словаря модерации: правка справочника доходит до всех процессов за минуту."""


class GeoDirectory:
    """Снимок: города по порядку списка, активные районы города по порядку, все районы по id."""

    def __init__(self, cities: Sequence[CityView], districts: Sequence[tuple[DistrictView, bool]]):
        self.cities = tuple(cities)
        self.city_by_id = {city.id: city for city in cities}
        self.active_of: dict[CityId, list[DistrictView]] = {}
        self.district_by_id: dict[DistrictId, DistrictSummary] = {}
        for district, active in districts:
            self.district_by_id[district.id] = DistrictSummary(
                id=district.id,
                city_id=district.city_id,
                slug=district.slug,
                name=district.name,
                center=district.center,
            )
            if active:
                self.active_of.setdefault(district.city_id, []).append(district)


async def _load(session: AsyncSession) -> GeoDirectory:
    query = SqlGeoQuery(session)
    return GeoDirectory(await query.cities(), await query.all_districts())


class GeoDirectoryCache(SnapshotCache[GeoDirectory]):
    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(maker, _load, name="geo", ttl=TTL)


class CachedGeoQuery(GeoQuery):
    """GeoQuery поверх снимка; промах по id и район точки — запросом в базу."""

    def __init__(self, cache: GeoDirectoryCache, sql: SqlGeoQuery) -> None:
        self._cache, self._sql = cache, sql

    async def cities(self) -> list[CityView]:
        return list((await self._cache.get()).data.cities)

    async def city(self, city_id: CityId) -> CityView | None:
        found = (await self._cache.get()).data.city_by_id.get(city_id)
        return found if found is not None else await self._sql.city(city_id)

    async def districts(self, city_id: CityId) -> list[DistrictView]:
        directory = (await self._cache.get()).data
        if city_id not in directory.city_by_id:
            return await self._sql.districts(city_id)
        return list(directory.active_of.get(city_id, ()))

    async def district(self, district_id: DistrictId) -> DistrictSummary | None:
        found = (await self._cache.get()).data.district_by_id.get(district_id)
        return found if found is not None else await self._sql.district(district_id)

    async def district_summaries(
        self, district_ids: Collection[DistrictId]
    ) -> dict[DistrictId, DistrictSummary]:
        known = (await self._cache.get()).data.district_by_id
        found = {i: known[i] for i in district_ids if i in known}
        missing = [i for i in district_ids if i not in known]
        if missing:
            found |= await self._sql.district_summaries(missing)
        return found

    async def resolve(self, point: GeoPoint) -> ResolvedPoint | None:
        return await self._sql.resolve(point)

    async def locate(self, city_id: CityId, point: GeoPoint) -> LocatedDistrict | None:
        return await self._sql.locate(city_id, point)

    async def representations(self) -> Memo:
        return (await self._cache.get()).memo
