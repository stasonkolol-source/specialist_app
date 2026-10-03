"""Read-model поиска из настоящего каталога для замеров и регрессии (DEVELOPMENT_PLAN 4.2, 4.3b).

Строки пишутся напрямую проектором (`SpecialistIndex.upsert`) — так, как их собирает проектор
4.1: названия, словарь и теги листовых категорий. `seed-demo` шёл бы через use cases и для
тысяч строк — часами, а выдача читает только read-model.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.catalog.api import CatalogApi, CategorySummary, SearchTerm
from app.modules.search.domain.index import IndexEntry, Labels, SearchDocument, serbian
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, UserId, new_id

SEEDS = Path(__file__).parents[2] / "seeds" / "catalog"
QUERIES = SEEDS / "queries.yaml"
"""Регрессионный набор «запрос → категория»: ru, sr, en, разговорные формы, опечатки."""
TAXONOMY = SEEDS / "taxonomy.yaml"
CENTER = GeoPoint(lat=45.2551, lon=19.8452)
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


def taxonomy_slugs() -> frozenset[str]:
    """Категории таксономии сидов — без тестовых, которые другие тесты кладут в ту же базу."""

    def walk(nodes: list[dict[str, Any]]) -> list[str]:
        return [slug for node in nodes for slug in (node["slug"], *walk(node.get("children", [])))]

    return frozenset(walk(yaml.safe_load(TAXONOMY.read_text())["categories"]))


async def leaves(container: AsyncContainer) -> list[Leaf]:
    """Активные листовые категории таксономии, которые видит поиск (без запрещённых)."""
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
    seeded = taxonomy_slugs()
    return [
        Leaf(
            id=CategoryId(row.id),
            slug=row.slug,
            path=tuple(row.path),
            document=document(summaries[CategoryId(row.id)], terms.get(CategoryId(row.id), ())),
        )
        for row in rows
        if row.slug in seeded
    ]


def document(category: CategorySummary, terms: tuple[SearchTerm, ...]) -> SearchDocument:
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


def row(rng: random.Random, leaf: Leaf, now: datetime, city: CityId) -> IndexEntry:
    """Специалист категории `leaf`: случайные имя, точка, цена, языки и формат."""
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    casual = rng.random() < 0.3
    point = GeoPoint(
        lat=CENTER.lat + rng.uniform(-0.08, 0.08), lon=CENTER.lon + rng.uniform(-0.08, 0.08)
    )
    doc = SearchDocument(
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
        city_id=city,
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
        rating_bayes=None,
        rating_lower_bound=None,
        rating_count=0,
        score=rng.random() * 0.1,
        name=name,
        document=doc,
        card={
            "display_name": name,
            "kind": "casual" if casual else "pro",
            "category_ids": [leaf.id],
        },
        source_updated_at=now,
    )
