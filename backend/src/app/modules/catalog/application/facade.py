"""Реализация CatalogApi для jobs, specialists, moderation и search (ADR-0020 §6)."""

from collections.abc import Collection

from app.modules.catalog.api import (
    CatalogApi,
    CategorySuggestion,
    CategorySummary,
    SearchTerm,
    TermMatch,
)
from app.modules.catalog.application.ports import CatalogQuery
from app.platform.kernel.ids import CategoryId


class CatalogFacade(CatalogApi):
    def __init__(self, query: CatalogQuery) -> None:
        self._query = query

    async def category(self, category_id: CategoryId) -> CategorySummary | None:
        return await self._query.category(category_id)

    async def categories(self, category_ids: Collection[CategoryId]) -> list[CategorySummary]:
        if not category_ids:
            return []
        return await self._query.categories(category_ids)

    async def search_terms(
        self, category_ids: Collection[CategoryId]
    ) -> dict[CategoryId, tuple[SearchTerm, ...]]:
        if not category_ids:
            return {}
        return await self._query.search_terms(category_ids)

    async def match_query(self, text: str) -> TermMatch | None:
        return await self._query.match_query(text) if text.strip() else None

    async def similar_term(self, text: str) -> TermMatch | None:
        return await self._query.similar_term(text) if text.strip() else None

    async def suggest(self, text: str, *, limit: int) -> list[CategorySuggestion]:
        return await self._query.suggest(text, limit=limit) if text.strip() else []
