"""Реализация CatalogApi для jobs, specialists, moderation и search (ADR-0020 §6)."""

from collections.abc import Collection

from app.modules.catalog.api import CatalogApi, CategorySummary
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
