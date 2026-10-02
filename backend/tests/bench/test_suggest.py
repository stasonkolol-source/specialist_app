"""Подсказки при вводе (DEVELOPMENT_PLAN 4.3a): p95 < 50 мс с кэшем.

Вручную: `uv run pytest -m bench -k suggest`. Ввод — начала (2–6 букв) запросов
регрессионного набора seeds/catalog/queries.yaml: так их набирают по буквам. Первый проход —
словарь (кэш пуст), второй — из кэша Valkey. Тест печатает p50 и p95 обоих.
"""

import statistics
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import yaml
from dishka import AsyncContainer
from redis.asyncio import Redis

from app.entrypoints._wiring import make_worker_container
from app.modules.search.application.use_cases.suggest_categories import (
    CACHE_KEY,
    SuggestCategories,
    SuggestCategoriesCommand,
)
from app.platform.cache.valkey import PREFIX
from app.platform.settings import Settings

pytestmark = pytest.mark.bench

QUERIES = Path(__file__).parents[2] / "seeds" / "catalog" / "queries.yaml"
TYPED = range(2, 7)
TARGET_P95_MS = 50.0


@pytest.fixture
async def container(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(storage_settings)
    try:
        valkey = await container.get(Redis)
        async for key in valkey.scan_iter(match=f"{PREFIX}{CACHE_KEY}*"):
            await valkey.delete(key)  # первый проход — без кэша
        yield container
    finally:
        await container.close()


def _inputs() -> list[str]:
    queries = yaml.safe_load(QUERIES.read_text())["queries"]
    typed = (item["q"][:length] for item in queries for length in TYPED)
    return list(dict.fromkeys(text for text in typed if len(text.strip()) >= min(TYPED)))


async def _pass(container: AsyncContainer, inputs: list[str]) -> list[float]:
    timings = []
    for typed in inputs:
        started = time.perf_counter()
        async with container() as request:
            await (await request.get(SuggestCategories))(SuggestCategoriesCommand(q=typed))
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def _p95(timings: list[float]) -> float:
    return statistics.quantiles(timings, n=20, method="inclusive")[-1]


async def test_suggest_p95_with_cache(
    container: AsyncContainer, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = _inputs()

    cold = await _pass(container, inputs)
    warm = await _pass(container, inputs)

    with capsys.disabled():
        print(
            f"\nsuggest: {len(inputs)} вводов; словарь — p50 {statistics.median(cold):.1f} мс,"
            f" p95 {_p95(cold):.1f} мс; из кэша — p50 {statistics.median(warm):.1f} мс,"
            f" p95 {_p95(warm):.1f} мс (порог p95 {TARGET_P95_MS:.0f} мс)"
        )
    assert _p95(warm) < TARGET_P95_MS
