"""Реальные сиды пилотной зоны в PostGIS (DEVELOPMENT_PLAN 1.3a): Нови-Сад и «скоро» Белград."""

import json

import procrastinate
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.entrypoints.seeds import load_city_seeds
from app.modules.geo.application.facade import GeoFacade
from app.modules.geo.application.use_cases.import_city import ImportCity, ImportCityCommand
from app.modules.geo.domain.place import CityStatus
from app.modules.geo.infrastructure.queries import SqlGeoQuery
from app.modules.geo.infrastructure.writer import SqlGeoWriter
from app.platform.kernel.localized import Locale
from tests.plugins.database import make_uow

pytestmark = pytest.mark.integration


async def _import(db_session: AsyncSession, app: procrastinate.App, seed):  # type: ignore[no-untyped-def]
    uow = make_uow(db_session, app)
    return await ImportCity(uow, SqlGeoWriter(db_session, uow))(ImportCityCommand(seed=seed))


async def test_repository_seeds_resolve_novi_sad(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    for seed in load_city_seeds():
        await _import(db_session, procrastinate_app, seed)
    query = SqlGeoQuery(db_session)
    liman = next(d for s in load_city_seeds() for d in s.districts if d.slug == "liman-3")
    resolved = await query.resolve(liman.center)
    assert resolved is not None
    assert resolved.district.slug == "liman-3"
    assert resolved.exact
    statuses = {c.slug: c.status for c in await query.cities()}
    assert statuses["novi-sad"] is CityStatus.ACTIVE
    assert statuses["beograd"] is CityStatus.SOON
    facade = GeoFacade(query)
    public = facade.public_point(liman.center, seed=b"job-1")
    assert public == facade.public_point(liman.center, seed=b"job-1") != liman.center
    summary = await facade.district(resolved.district.id)
    assert summary is not None
    assert summary.name.get(Locale.SR_LATN) == "Liman 3"
    assert json.dumps(summary.center.lat)
