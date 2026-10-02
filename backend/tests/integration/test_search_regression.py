"""Регрессионный набор поиска (DEVELOPMENT_PLAN 4.3b): «запрос → категория» на настоящем каталоге.

Запросы — seeds/catalog/queries.yaml: как пишут люди — ru, sr латиницей и кириллицей, en,
разговорные формы, опечатки и транслит. Read-model — по три специалиста на каждую листовую
категорию, строки — как их собирает проектор 4.1. Первая карточка выдачи должна быть из
ожидаемой категории не реже порога: 95% предложено владельцу (K21). Тест печатает долю и
промахи — их разбор пополняет словарь категорий (seeds/catalog).
"""

import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Final

import pytest
import yaml
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import make_worker_container
from app.modules.search.application.dto import SpecialistFilters
from app.modules.search.application.ports import SpecialistIndex
from app.modules.search.application.use_cases.search_specialists import (
    SearchSpecialists,
    SearchSpecialistsCommand,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CityId
from app.platform.settings import Settings
from tests.plugins.search_lab import QUERIES, leaves, row

pytestmark = pytest.mark.integration

THRESHOLD: Final = 0.95
"""Доля запросов, где первая карточка из ожидаемой категории (K21: предложение владельцу)."""
PER_LEAF: Final = 3
MIN_QUERIES: Final = 200
CITY = CityId(990_002)


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


async def test_search_regression_finds_the_expected_category(
    container: AsyncContainer, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = await leaves(container)
    rng = random.Random(7)  # noqa: S311 — данные теста, не криптография
    now = datetime.now(UTC)
    rows = [row(rng, leaf, now, CITY) for leaf in catalog for _ in range(PER_LEAF)]
    async with container() as request:
        uow, index = await request.get(UnitOfWork), await request.get(SpecialistIndex)
        async with uow:
            await index.upsert(rows)
    slugs = {leaf.id: leaf.slug for leaf in catalog}
    queries = yaml.safe_load(QUERIES.read_text())["queries"]

    misses: list[str] = []
    for item in queries:
        async with container() as request:
            search = await request.get(SearchSpecialists)
            results = await search(
                SearchSpecialistsCommand(filters=SpecialistFilters(city_id=CITY), q=item["q"])
            )
        first = results.page.items[0] if results.page.items else None
        found = slugs.get(first.category_ids[0]) if first and first.category_ids else None
        if found != item["category"]:
            misses.append(f"  {item['q']!r}: ждали {item['category']}, первая — {found or 'пусто'}")

    rate = 1 - len(misses) / len(queries)
    with capsys.disabled():
        print(f"\nsearch_regression: {len(queries)} запросов, попаданий {rate:.1%}")
        print("\n".join(misses))
    assert len(queries) >= MIN_QUERIES
    assert rate >= THRESHOLD
