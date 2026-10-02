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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import make_worker_container
from app.modules.catalog.api import CatalogApi, CategorySummary, SearchTerm
from app.modules.search.application.dto import SpecialistFilters, SpecialistResults
from app.modules.search.application.ports import SpecialistIndex
from app.modules.search.application.use_cases.search_specialists import (
    SearchSpecialists,
    SearchSpecialistsCommand,
)
from app.modules.search.domain.index import IndexEntry, Labels, SearchDocument, serbian
from app.modules.search.domain.query import SpecialistSort
from app.platform.db.port import UnitOfWork
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, UserId, new_id
from app.platform.settings import Settings

pytestmark = pytest.mark.bench

ROWS = 50_000
BATCH = 1_000
ROUNDS = 3
TARGET_P95_MS = 200.0
CITY = CityId(990_001)
CENTER = GeoPoint(lat=45.2551, lon=19.8452)
QUERIES = Path(__file__).parents[2] / "seeds" / "catalog" / "queries.yaml"
FIRST = (
    "Marko",
    "Nikola",
    "Ana",
    "Jelena",
    "Иван",
    "Ольга",
    "Dmitrij",
    "Milica",
    "Stefan",
    "Мария",
)
LAST = ("Petrović", "Jovanović", "Nikolić", "Иванов", "Смирнова", "Popović", "Kovačević", "Ilić")
GROUPS = {"ru": ("ru",), "sr": ("sr-Latn", "sr-Cyrl"), "en": ("en",)}


@dataclass(frozen=True, slots=True)
class Leaf:
    id: CategoryId
    slug: str
    path: tuple[CategoryId, ...]
    document: SearchDocument


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


async def _leaves(container: AsyncContainer) -> list[Leaf]:
    engine = await container.get(AsyncEngine)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT c.id, c.slug, c.path FROM catalog.categories c"
                    " WHERE c.is_active AND c.risk_level < 3 AND NOT EXISTS ("
                    "  SELECT 1 FROM catalog.categories k WHERE k.parent_id = c.id"
                    "  AND k.is_active)"
                )
            )
        ).all()
    async with container() as request:
        catalog = await request.get(CatalogApi)
        ids = [CategoryId(row.id) for row in rows]
        summaries = {c.id: c for c in await catalog.categories(ids)}
        terms = await catalog.search_terms(ids)
    return [
        Leaf(
            id=CategoryId(row.id),
            slug=row.slug,
            path=tuple(row.path),
            document=_document(summaries[CategoryId(row.id)], terms.get(CategoryId(row.id), ())),
        )
        for row in rows
    ]


def _document(category: CategorySummary, terms: tuple[SearchTerm, ...]) -> SearchDocument:
    """Как документ проектора 4.1 (без имени — его добавит строка)."""
    names, synonyms = Labels(), Labels()
    for locale, name in category.name.values.items():
        names.add(locale.value, name)
    for term in terms:
        synonyms.add(term.lang.value, term.term)
    return SearchDocument(
        names_ru=names.joined(*GROUPS["ru"]),
        names_sr=serbian(names.joined(*GROUPS["sr"])),
        names_en=names.joined(*GROUPS["en"]),
        terms_ru=synonyms.joined(*GROUPS["ru"]),
        terms_sr=serbian(synonyms.joined(*GROUPS["sr"])),
        terms_en=synonyms.joined(*GROUPS["en"]),
    )


def _row(rng: random.Random, leaf: Leaf, now: datetime) -> IndexEntry:
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    casual = rng.random() < 0.3
    point = GeoPoint(
        lat=CENTER.lat + rng.uniform(-0.08, 0.08), lon=CENTER.lon + rng.uniform(-0.08, 0.08)
    )
    document = SearchDocument(
        names_ru=f"{name} ; {leaf.document.names_ru}",
        names_sr=serbian(f"{name} ; {leaf.document.names_sr}"),
        names_en=leaf.document.names_en,
        terms_ru=leaf.document.terms_ru,
        terms_sr=leaf.document.terms_sr,
        terms_en=leaf.document.terms_en,
    )
    price = rng.choice((None, rng.randrange(50_000, 500_000, 10_000)))
    return IndexEntry(
        profile_id=new_id(),
        user_id=UserId(new_id()),
        kind="casual" if casual else "pro",
        is_listed=not casual,
        city_id=CITY,
        district_id=None,
        district_ids=(),
        base_point=point,
        base_point_public=point,
        travel_radius_m=rng.choice((None, 3_000, 5_000, 10_000)),
        category_ids=tuple(sorted(set(leaf.path))),
        languages=tuple(rng.sample(("ru", "sr", "en", "uk"), rng.randint(1, 3))),
        work_modes=tuple(rng.sample(("at_client", "at_own_place", "remote"), rng.randint(1, 2))),
        price_from=price,
        category_prices={leaf.id: price} if price is not None else {},
        available_until=now + timedelta(hours=3) if rng.random() < 0.3 else None,
        activity_score=rng.random(),
        score=rng.random() * 0.1,
        name=name,
        document=document,
        card={
            "display_name": name,
            "kind": "casual" if casual else "pro",
            "category_ids": [leaf.id],
        },
        source_updated_at=now,
    )


async def _seed(container: AsyncContainer, leaves: list[Leaf]) -> None:
    rng = random.Random(42)  # noqa: S311 — объём для замера, не криптография
    now = datetime.now(UTC)
    for start in range(0, ROWS, BATCH):
        rows = [_row(rng, rng.choice(leaves), now) for _ in range(start, start + BATCH)]
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
    leaves = await _leaves(container)
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
