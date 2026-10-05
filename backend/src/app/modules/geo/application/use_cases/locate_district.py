"""Район по точке (S20b «Определить по геолокации», булавка на карте): квартал города клиента.

Приватность (ARCHITECTURE §7.6): координаты нужны только на время запроса — они не сохраняются
и не пишутся в лог, в том числе в параметрах ошибок. В логе — город, найденный район и исход.
"""

from dataclasses import dataclass

import structlog

from app.modules.geo.application.dto import DistrictView
from app.modules.geo.application.ports import GeoQuery
from app.modules.geo.errors import CityNotFoundError, OutsideCityError
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class LocateDistrictCommand:
    city_id: CityId
    point: GeoPoint


class LocateDistrict:
    def __init__(self, query: GeoQuery) -> None:
        self._query = query

    async def __call__(self, cmd: LocateDistrictCommand) -> DistrictView:
        if await self._query.city(cmd.city_id) is None:
            raise CityNotFoundError(city_id=cmd.city_id)
        located = await self._query.locate(cmd.city_id, cmd.point)
        if located is None:
            log.info("district_locate", city_id=cmd.city_id, outcome="outside_city")
            raise OutsideCityError(city_id=cmd.city_id)
        log.info(
            "district_locate",
            city_id=cmd.city_id,
            district_id=located.district.id,
            outcome="inside" if located.exact else "nearest",
        )
        return located.district
