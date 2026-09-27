"""Сиды пилотной зоны в БД сессии тестов (идемпотентно, как `cli seed`)."""

import pytest

from app.entrypoints._wiring import make_worker_container
from app.entrypoints.seeds import load_city_seeds
from app.modules.geo.application.use_cases.import_city import ImportCity, ImportCityCommand
from app.platform.settings import Settings


@pytest.fixture
async def geo_seeded(settings: Settings) -> None:
    container = make_worker_container(settings)
    try:
        for seed in load_city_seeds():
            async with container() as request:
                await (await request.get(ImportCity))(ImportCityCommand(seed=seed))
    finally:
        await container.close()
