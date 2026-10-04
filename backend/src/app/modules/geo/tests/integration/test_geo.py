"""Импорт сидов и район точки на PostGIS (DEVELOPMENT_PLAN 1.3a)."""

import procrastinate
import pytest
from shapely.geometry import MultiPolygon, box
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.plugins.database import make_uow

from app.modules.geo.application.dto import CitySeed, DistrictSeed, ImportResult
from app.modules.geo.application.facade import GeoFacade
from app.modules.geo.application.use_cases.import_city import ImportCity, ImportCityCommand
from app.modules.geo.domain.place import CityStatus, DistrictKind
from app.modules.geo.infrastructure.queries import SqlGeoQuery
from app.modules.geo.infrastructure.writer import SqlGeoWriter
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.testing.cache import NoSnapshotCache

pytestmark = pytest.mark.integration

# Синтетический город у экватора: квадраты 0,01° ≈ 1,1 км.
CITY_CENTER = GeoPoint(lat=0.015, lon=0.015)


def square(x: float, y: float, size: float = 0.01) -> str:
    return MultiPolygon([box(x, y, x + size, y + size)]).wkt


def district(
    slug: str, kind: DistrictKind, parent: str | None, wkt: str | None, center: GeoPoint
) -> DistrictSeed:
    return DistrictSeed(
        slug=slug,
        kind=kind,
        parent=parent,
        name=LocalizedText({Locale.RU: slug, Locale.SR_CYRL: "Лиман"}),
        aliases=(),
        center=center,
        boundary_wkt=wkt,
        source="test",
    )


def a_city(slug: str = "test-city", *, active: bool = True, name: str = "Тест") -> CitySeed:
    return CitySeed(
        slug=slug,
        name=LocalizedText({Locale.RU: name, Locale.SR_CYRL: "Тест"}),
        center=CITY_CENTER,
        active=active,
        sort_order=9,
        boundary_wkt=square(0, 0, 0.03),
        districts=(
            district("whole", DistrictKind.MUNICIPALITY, None, square(0, 0, 0.03), CITY_CENTER),
            district(
                "north",
                DistrictKind.NEIGHBORHOOD,
                "whole",
                square(0, 0.02),
                GeoPoint(lat=0.025, lon=0.005),
            ),
            district(
                "south",
                DistrictKind.NEIGHBORHOOD,
                "whole",
                square(0, 0),
                GeoPoint(lat=0.005, lon=0.005),
            ),
            district(
                "no-polygon", DistrictKind.NEIGHBORHOOD, "whole", None, GeoPoint(lat=0.05, lon=0.05)
            ),
        ),
    )


async def _import(db_session: AsyncSession, app: procrastinate.App, seed: CitySeed) -> ImportResult:
    uow = make_uow(db_session, app)
    import_city = ImportCity(uow, SqlGeoWriter(db_session, uow), NoSnapshotCache())
    return await import_city(ImportCityCommand(seed=seed))


async def test_import_is_idempotent_and_generates_latin(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    first = await _import(db_session, procrastinate_app, a_city())
    again = await _import(db_session, procrastinate_app, a_city())
    renamed = await _import(db_session, procrastinate_app, a_city(name="Переименован"))
    assert (first.created, first.updated, first.unchanged) == (5, 0, 0)
    assert (again.created, again.updated, again.unchanged) == (0, 0, 5)
    assert (renamed.created, renamed.updated, renamed.unchanged) == (0, 1, 4)
    [city] = [c for c in await SqlGeoQuery(db_session).cities() if c.slug == "test-city"]
    assert city.name.values[Locale.SR_LATN] == "Test"
    assert city.status is CityStatus.ACTIVE


@pytest.mark.parametrize(
    ("point", "slug", "exact"),
    [
        (GeoPoint(lat=0.025, lon=0.005), "north", True),
        (GeoPoint(lat=0.005, lon=0.005), "south", True),
        (GeoPoint(lat=0.015, lon=0.025), "whole", True),  # внутри города, вне кварталов
        (GeoPoint(lat=0.049, lon=0.049), "no-polygon", False),  # вне полигонов: ближайший центр
        (GeoPoint(lat=0.045, lon=-0.01), "north", False),
    ],
)
async def test_point_resolves_to_district(
    db_session: AsyncSession,
    procrastinate_app: procrastinate.App,
    point: GeoPoint,
    slug: str,
    exact: bool,
) -> None:
    await _import(db_session, procrastinate_app, a_city())
    resolved = await SqlGeoQuery(db_session).resolve(point)
    assert resolved is not None
    assert (resolved.district.slug, resolved.exact) == (slug, exact)


async def test_far_points_and_inactive_cities_are_outside(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, a_city())
    assert await SqlGeoQuery(db_session).resolve(GeoPoint(lat=1.0, lon=1.0)) is None
    # город выключает админка (2.7b): `active` из сида задаёт только новую строку
    await db_session.execute(
        text("UPDATE geo.cities SET is_active = false WHERE slug = 'test-city'")
    )
    await db_session.commit()  # правка админки — своя транзакция (здесь — savepoint теста)
    assert await SqlGeoQuery(db_session).resolve(GeoPoint(lat=0.005, lon=0.005)) is None


async def test_facade_reports_city_and_its_status(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    """Город из онбординга identity проверяет через фасад (DEVELOPMENT_PLAN 1.4a)."""
    await _import(db_session, procrastinate_app, a_city())
    await _import(db_session, procrastinate_app, a_city("soon-city", active=False))
    query = SqlGeoQuery(db_session)
    ids = {c.slug: c.id for c in await query.cities()}
    facade = GeoFacade(query)

    active = await facade.city(ids["test-city"])
    soon = await facade.city(ids["soon-city"])
    assert active is not None
    assert (active.slug, active.is_active) == ("test-city", True)
    assert active.name.get(Locale.RU) == "Тест"
    assert soon is not None
    assert not soon.is_active
    assert await facade.city(CityId(999_999)) is None
