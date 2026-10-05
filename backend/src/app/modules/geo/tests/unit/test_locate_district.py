"""Район по точке (S20b, карта): город, исход и приватность — координат нет в логе."""

from collections.abc import Collection

import pytest
from structlog.testing import capture_logs

from app.modules.geo.api import DistrictSummary, ResolvedPoint
from app.modules.geo.application.dto import CityView, DistrictView, LocatedDistrict
from app.modules.geo.application.use_cases.locate_district import (
    LocateDistrict,
    LocateDistrictCommand,
)
from app.modules.geo.domain.place import CityStatus, DistrictKind
from app.modules.geo.errors import CityNotFoundError, OutsideCityError
from app.platform.cache.memo import Memo
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId, DistrictId
from app.platform.kernel.localized import Locale, LocalizedText

pytestmark = pytest.mark.unit

CITY = CityView(
    id=CityId(1),
    slug="novi-sad",
    name=LocalizedText({Locale.RU: "Нови-Сад", Locale.SR_CYRL: "Нови Сад"}),
    center=GeoPoint(lat=45.2671, lon=19.8335),
    status=CityStatus.ACTIVE,
)
LIMAN = DistrictView(
    id=DistrictId(7),
    city_id=CITY.id,
    parent_id=None,
    kind=DistrictKind.NEIGHBORHOOD,
    slug="liman-3",
    name=LocalizedText({Locale.RU: "Лиман 3", Locale.SR_CYRL: "Лиман 3"}),
    center=GeoPoint(lat=45.2398, lon=19.8378),
)
POINT = GeoPoint(lat=45.239713, lon=19.835041)


class FakeQuery:
    """GeoQuery теста: один город и заданный ответ `locate`; запоминает, о чём спросили."""

    def __init__(self, located: LocatedDistrict | None) -> None:
        self.located = located
        self.asked: list[tuple[CityId, GeoPoint]] = []

    async def cities(self) -> list[CityView]:
        return [CITY]

    async def city(self, city_id: CityId) -> CityView | None:
        return CITY if city_id == CITY.id else None

    async def districts(self, city_id: CityId) -> list[DistrictView]:
        return [LIMAN]

    async def district(self, district_id: DistrictId) -> DistrictSummary | None:
        return None

    async def district_summaries(
        self, district_ids: Collection[DistrictId]
    ) -> dict[DistrictId, DistrictSummary]:
        return {}

    async def resolve(self, point: GeoPoint) -> ResolvedPoint | None:
        return None

    async def locate(self, city_id: CityId, point: GeoPoint) -> LocatedDistrict | None:
        self.asked.append((city_id, point))
        return self.located

    async def representations(self) -> Memo:
        return Memo()


@pytest.mark.parametrize(("exact", "outcome"), [(True, "inside"), (False, "nearest")])
async def test_point_gives_district_and_only_outcome_is_logged(exact: bool, outcome: str) -> None:
    query = FakeQuery(LocatedDistrict(district=LIMAN, exact=exact))
    with capture_logs() as logs:
        found = await LocateDistrict(query)(LocateDistrictCommand(city_id=CITY.id, point=POINT))
    assert found == LIMAN
    assert query.asked == [(CITY.id, POINT)]
    assert logs == [
        {
            "event": "district_locate",
            "log_level": "info",
            "city_id": CITY.id,
            "district_id": LIMAN.id,
            "outcome": outcome,
        }
    ]
    assert "45.2397" not in repr(logs)
    assert "19.835" not in repr(logs)


async def test_point_outside_city_is_404_without_coordinates() -> None:
    query = FakeQuery(None)
    with capture_logs() as logs, pytest.raises(OutsideCityError) as raised:
        await LocateDistrict(query)(LocateDistrictCommand(city_id=CITY.id, point=POINT))
    assert raised.value.code == "outside_city"
    # параметры ошибки уходят в лог обработчика ошибок: координат в них нет
    assert raised.value.params == {"city_id": CITY.id}
    assert [entry["outcome"] for entry in logs] == ["outside_city"]
    assert "45.2397" not in repr(logs) + str(raised.value)


async def test_unknown_city_is_city_not_found_and_point_is_not_looked_up() -> None:
    query = FakeQuery(LocatedDistrict(district=LIMAN, exact=True))
    with pytest.raises(CityNotFoundError):
        await LocateDistrict(query)(LocateDistrictCommand(city_id=CityId(999), point=POINT))
    assert query.asked == []
