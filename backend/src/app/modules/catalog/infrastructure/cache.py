"""Таксономия в памяти процесса (перф-аудит 2026-10): дерево категорий и сводки по id.

Дерево отдаёт GET /categories на каждом запуске, а названия категорий нужны карточкам S08, S11 и
прайсу S09; меняет таксономию только импорт сидов (и админка). Снимок — два запроса — живёт
минуту (platform/cache/snapshot.py), как словарь модерации: столько же правка доходит до всех
процессов. Чего нет в снимке (категория добавлена после него), читается из базы. Поиск по
словарю (подсказки, триграммы) — по-прежнему запросами.
"""

from collections.abc import Collection, Sequence
from datetime import timedelta
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.catalog.api import CategorySuggestion, CategorySummary, SearchTerm, TermMatch
from app.modules.catalog.application.dto import CategoryView
from app.modules.catalog.application.ports import CatalogQuery
from app.modules.catalog.infrastructure.queries import SqlCatalogQuery
from app.platform.cache.memo import Memo
from app.platform.cache.snapshot import SnapshotCache
from app.platform.kernel.ids import CategoryId

TTL: Final = timedelta(seconds=60)


class Taxonomy:
    """Снимок: публичное дерево, все категории по id и города с ориентирами цены."""

    def __init__(self, tree: Sequence[CategoryView], categories: Sequence[CategorySummary]):
        self.tree = tuple(tree)
        self.by_id = {category.id: category for category in categories}
        self.hint_cities = frozenset(_hint_cities(self.tree))


def _hint_cities(nodes: Sequence[CategoryView]) -> set[str]:
    found: set[str] = set()
    for node in nodes:
        found.update(node.price_hints)
        found |= _hint_cities(node.children)
    return found


async def _load(session: AsyncSession) -> Taxonomy:
    return Taxonomy(*await SqlCatalogQuery(session).taxonomy())


class TaxonomySnapshotCache(SnapshotCache[Taxonomy]):
    def __init__(self, maker: async_sessionmaker[AsyncSession]) -> None:
        super().__init__(maker, _load, name="catalog", ttl=TTL)


class CachedCatalogQuery(CatalogQuery):
    """CatalogQuery поверх снимка: дерево и категории по id; промах и словарь — запросами."""

    def __init__(self, cache: TaxonomySnapshotCache, sql: SqlCatalogQuery) -> None:
        self._cache, self._sql = cache, sql

    async def tree(self) -> list[CategoryView]:
        return list((await self._cache.get()).data.tree)

    async def category(self, category_id: CategoryId) -> CategorySummary | None:
        found = (await self._cache.get()).data.by_id.get(category_id)
        return found if found is not None else await self._sql.category(category_id)

    async def categories(self, category_ids: Collection[CategoryId]) -> list[CategorySummary]:
        known = (await self._cache.get()).data.by_id
        found = [known[i] for i in dict.fromkeys(category_ids) if i in known]
        missing = [i for i in category_ids if i not in known]
        if missing:
            found += await self._sql.categories(missing)
        return sorted(found, key=lambda category: category.path)

    async def search_terms(
        self, category_ids: Collection[CategoryId]
    ) -> dict[CategoryId, tuple[SearchTerm, ...]]:
        return await self._sql.search_terms(category_ids)

    async def match_query(self, text: str) -> TermMatch | None:
        return await self._sql.match_query(text)

    async def similar_term(self, text: str) -> TermMatch | None:
        return await self._sql.similar_term(text)

    async def suggest(self, text: str, *, limit: int) -> list[CategorySuggestion]:
        return await self._sql.suggest(text, limit=limit)

    async def representations(self) -> Memo:
        return (await self._cache.get()).memo

    async def price_hint_cities(self) -> frozenset[str]:
        return (await self._cache.get()).data.hint_cities
