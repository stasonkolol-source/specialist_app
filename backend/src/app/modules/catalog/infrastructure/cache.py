"""Таксономия в памяти процесса (перф-аудит 2026-10): дерево категорий и названия по id.

Дерево отдаёт GET /categories на каждом запуске, а названия категорий нужны карточкам S08, S11 и
прайсу S09; меняет таксономию только импорт сидов (и админка). Снимок — два запроса — живёт
минуту (platform/cache/snapshot.py), как словарь модерации: столько же правка доходит до всех
процессов. Чего нет в снимке (категория добавлена после него), читается из базы.

Категории для решений (`category`, `categories`: риск для модерации, «можно ли заявку», путь в
заявке и в индексе поиска) читаются из базы, как раньше: переиндексация по CatalogChanged
не должна взять отстающий снимок.

Распознанный текст запроса (словарь целиком или по началу, ближайшее слово) запоминается в
снимке: один и тот же запрос выдачи и её счётчика («Показать N») не ходит в словарь дважды, а
обновление снимка сбрасывает и эти ответы. Подсказки при вводе — запросами (у них свой кэш в
Valkey).
"""

from collections.abc import Awaitable, Callable, Collection, Sequence
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
from app.platform.kernel.localized import LocalizedText

TTL: Final = timedelta(seconds=60)
MAX_MATCHES: Final = 1024
"""Распознанных текстов на снимок не больше: ввод клиента не должен раздувать память."""


class Taxonomy:
    """Снимок: публичное дерево, названия всех категорий по id и города с ориентирами цены."""

    def __init__(self, tree: Sequence[CategoryView], categories: Sequence[CategorySummary]):
        self.tree = tuple(tree)
        self.labels = {category.id: category.name for category in categories}
        self.hint_cities = frozenset(_hint_cities(self.tree))
        self.matches: dict[tuple[str, str], TermMatch | None] = {}


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
    """CatalogQuery поверх снимка: дерево, названия и распознанный текст; остальное — запросами."""

    def __init__(self, cache: TaxonomySnapshotCache, sql: SqlCatalogQuery) -> None:
        self._cache, self._sql = cache, sql

    async def tree(self) -> list[CategoryView]:
        return list((await self._cache.get()).data.tree)

    async def category(self, category_id: CategoryId) -> CategorySummary | None:
        return await self._sql.category(category_id)

    async def categories(self, category_ids: Collection[CategoryId]) -> list[CategorySummary]:
        return await self._sql.categories(category_ids)

    async def labels(self, category_ids: Collection[CategoryId]) -> dict[CategoryId, LocalizedText]:
        known = (await self._cache.get()).data.labels
        found = {i: known[i] for i in category_ids if i in known}
        missing = [i for i in category_ids if i not in known]
        if missing:
            found |= await self._sql.labels(missing)
        return found

    async def search_terms(
        self, category_ids: Collection[CategoryId]
    ) -> dict[CategoryId, tuple[SearchTerm, ...]]:
        return await self._sql.search_terms(category_ids)

    async def match_query(self, text: str) -> TermMatch | None:
        return await self._remembered("match", text, self._sql.match_query)

    async def similar_term(self, text: str) -> TermMatch | None:
        return await self._remembered("similar", text, self._sql.similar_term)

    async def suggest(self, text: str, *, limit: int) -> list[CategorySuggestion]:
        return await self._sql.suggest(text, limit=limit)

    async def representations(self) -> Memo:
        return (await self._cache.get()).memo

    async def price_hint_cities(self) -> frozenset[str]:
        return (await self._cache.get()).data.hint_cities

    async def _remembered(
        self, kind: str, text: str, load: Callable[[str], Awaitable[TermMatch | None]]
    ) -> TermMatch | None:
        matches = (await self._cache.get()).data.matches
        key = (kind, text)
        if key in matches:
            return matches[key]
        found = await load(text)
        if len(matches) < MAX_MATCHES:
            matches[key] = found
        return found
