"""Порты модуля catalog (ADR-0020 §3, §5). Справочник: запись только импортом сидов и админкой."""

from collections.abc import Collection, Sequence
from typing import Protocol

from app.modules.catalog.api import CategorySuggestion, CategorySummary, SearchTerm, TermMatch
from app.modules.catalog.application.dto import CategorySeed, CategoryView, ImportResult
from app.platform.kernel.ids import CategoryId


class CatalogQuery(Protocol):
    async def tree(self) -> list[CategoryView]:
        """Публичное дерево: активные и не запрещённые категории, по sort_order."""
        ...

    async def category(self, category_id: CategoryId) -> CategorySummary | None: ...

    async def categories(self, category_ids: Collection[CategoryId]) -> list[CategorySummary]: ...

    async def search_terms(
        self, category_ids: Collection[CategoryId]
    ) -> dict[CategoryId, tuple[SearchTerm, ...]]: ...

    async def match_query(self, text: str) -> TermMatch | None: ...

    async def similar_term(self, text: str) -> TermMatch | None: ...

    async def suggest(self, text: str, *, limit: int) -> list[CategorySuggestion]: ...


class CatalogWriter(Protocol):
    async def import_taxonomy(self, categories: Sequence[CategorySeed]) -> ImportResult:
        """Идемпотентно: неизменённые категории с тегами и словарём не трогаются."""
        ...
