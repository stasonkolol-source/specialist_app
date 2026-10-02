"""Выдача специалистов на объёме лаборатории (DEVELOPMENT_PLAN 4.2): p95 < 200 мс.

Вручную: `make bench-search` (`uv run pytest -m bench -k search_query`). 50 000 строк
read-model из настоящего каталога: названия, словарь и теги категорий — как их пишет проектор
4.1. `seed-demo --scale lab` шёл бы часами через use cases, а выдача читает только read-model.
Запросы — регрессионный набор seeds/catalog/queries.yaml (ru, sr, en, разговорные формы) и
просмотр без текста с фильтрами и сортировками. Тест печатает p50, p95, максимум и долю
запросов, где первая карточка из ожидаемой категории (качество проверяет 4.3b).
"""

import random
import statistics
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import yaml
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import make_worker_container
from app.modules.search.application.dto import SpecialistFilters, SpecialistResults
from app.modules.search.application.ports import SpecialistIndex
from app.modules.search.application.use_cases.search_specialists import (
    SearchSpecialists,
    SearchSpecialistsCommand,
)
from app.modules.search.domain.query import SpecialistSort
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CityId
from app.platform.settings import Settings
from tests.plugins.search_lab import CENTER, QUERIES, Leaf, row
from tests.plugins.search_lab import leaves as lab_leaves

pytestmark = pytest.mark.bench

ROWS = 50_000
BATCH = 1_000
ROUNDS = 3
TARGET_P95_MS = 200.0
CITY = CityId(990_001)


@pytest.fixture
async def container(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(storage_settings)
    try:
        yield container
    finally:
        engine = await container.get(AsyncEngine)
        async with engine.begin() as conn:
            for table in ("specialist_index", "query_log"):
                await conn.execute(
                    text(f"DELETE FROM search.{table} WHERE city_id = :c"), {"c": CITY}
                )
        await container.close()


async def _seed(container: AsyncContainer, leaves: list[Leaf]) -> None:
    rng = random.Random(42)  # noqa: S311 — объём для замера, не криптография
    now = datetime.now(UTC)
    for start in range(0, ROWS, BATCH):
        rows = [row(rng, rng.choice(leaves), now, CITY) for _ in range(start, start + BATCH)]
        async with container() as request:
            uow, index = await request.get(UnitOfWork), await request.get(SpecialistIndex)
            async with uow:
                await index.upsert(rows)
    engine = await container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(text("ANALYZE search.specialist_index"))


def _commands(leaves: list[Leaf]) -> list[tuple[SearchSpecialistsCommand, str | None]]:
    queries = yaml.safe_load(QUERIES.read_text())["queries"]
    some = leaves[len(leaves) // 2]
    base = SpecialistFilters(city_id=CITY)
    near = SpecialistFilters(city_id=CITY, point=CENTER)
    browse: list[dict[str, Any]] = [
        {},
        {"filters": SpecialistFilters(city_id=CITY, category_id=some.id)},
        {"filters": SpecialistFilters(city_id=CITY, point=CENTER, radius_m=3_000)},
        {"filters": SpecialistFilters(city_id=CITY, point=CENTER, travels_to_me=True)},
        {
            "filters": SpecialistFilters(city_id=CITY, category_id=some.id, price_max=200_000),
            "sort": SpecialistSort.PRICE,
        },
        {"filters": near, "sort": SpecialistSort.DISTANCE},
        {"filters": SpecialistFilters(city_id=CITY, available_today=True)},
        {"sort": SpecialistSort.RATING},
    ]
    commands = [
        (SearchSpecialistsCommand(filters=base, q=item["q"]), item["category"]) for item in queries
    ]
    commands += [
        (SearchSpecialistsCommand(**({"filters": base} | params)), None) for params in browse
    ]
    return commands


async def _timed(
    container: AsyncContainer, command: SearchSpecialistsCommand
) -> tuple[float, SpecialistResults]:
    started = time.perf_counter()
    async with container() as request:
        results = await (await request.get(SearchSpecialists))(command)
    return (time.perf_counter() - started) * 1000, results


async def test_search_query_p95(
    container: AsyncContainer, capsys: pytest.CaptureFixture[str]
) -> None:
    leaves = await lab_leaves(container)
    started = time.monotonic()
    await _seed(container, leaves)
    seeded = time.monotonic() - started
    slugs = {leaf.slug: leaf.id for leaf in leaves}
    commands = _commands(leaves)
    for command, _ in commands:  # прогрев: планы и кэши
        await _timed(container, command)

    timings: list[float] = []
    hits = expected = 0
    for _ in range(ROUNDS):
        for command, slug in commands:
            elapsed, results = await _timed(container, command)
            timings.append(elapsed)
            if slug is not None:
                expected += 1
                items = results.page.items
                hits += bool(items) and slugs[slug] in items[0].category_ids

    p50 = statistics.median(timings)
    p95 = statistics.quantiles(timings, n=20, method="inclusive")[-1]
    with capsys.disabled():
        print(
            f"\nsearch_query: {ROWS} строк за {seeded:.0f} с; {len(commands)} запросов × {ROUNDS};"
            f" p50 {p50:.1f} мс, p95 {p95:.1f} мс, максимум {max(timings):.1f} мс"
            f" (порог p95 {TARGET_P95_MS:.0f} мс); первая карточка из ожидаемой категории —"
            f" {hits / expected:.0%} запросов набора"
        )
    assert p95 < TARGET_P95_MS
