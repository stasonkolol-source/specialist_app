"""Чтение справочника catalog (ADR-0020 §5): публичное дерево и категории для фасада."""

from collections import defaultdict
from collections.abc import Collection, Sequence

from sqlalchemy import select
from sqlalchemy.engine import RowMapping

from app.modules.catalog.api import CategorySummary, RiskLevel
from app.modules.catalog.application.dto import CategoryNode, TagView
from app.modules.catalog.infrastructure.models import CategoryRow, TagRow
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import CategoryId, TagId

_CATEGORIES = CategoryRow.__table__.c
_SUMMARY = (
    _CATEGORIES.id,
    _CATEGORIES.parent_id,
    _CATEGORIES.slug,
    _CATEGORIES.name,
    _CATEGORIES.path,
    _CATEGORIES.risk_level,
    _CATEGORIES.is_active,
    _CATEGORIES.jobs_enabled,
    _CATEGORIES.max_responses,
)


class SqlCatalogQuery(SqlQuery):
    async def tree(self) -> list[CategoryNode]:
        c, t = _CATEGORIES, TagRow.__table__.c
        categories = await self._fetch(
            select(c.id, c.parent_id, c.slug, c.name, c.icon, c.price_hint)
            .where(c.is_active, c.risk_level < int(RiskLevel.FORBIDDEN))
            .order_by(c.sort_order, c.id)
        )
        tags = await self._fetch(
            select(t.id, t.category_id, t.slug, t.name).where(t.is_active).order_by(t.id)
        )
        return _tree(categories, tags)

    async def category(self, category_id: CategoryId) -> CategorySummary | None:
        row = await self._fetch_one(select(*_SUMMARY).where(_CATEGORIES.id == category_id))
        return _summary(row) if row is not None else None

    async def categories(self, category_ids: Collection[CategoryId]) -> list[CategorySummary]:
        rows = await self._fetch(
            select(*_SUMMARY)
            .where(_CATEGORIES.id.in_(list(category_ids)))
            .order_by(_CATEGORIES.path)
        )
        return [_summary(row) for row in rows]


def _tree(categories: Sequence[RowMapping], tags: Sequence[RowMapping]) -> list[CategoryNode]:
    """Дерево из плоских строк: потомки выключенной категории в него не попадают."""
    tags_of: defaultdict[int, list[TagView]] = defaultdict(list)
    for tag in tags:
        tags_of[tag["category_id"]].append(
            TagView(id=TagId(tag["id"]), slug=tag["slug"], name=tag["name"])
        )
    children_of: defaultdict[int | None, list[RowMapping]] = defaultdict(list)
    for row in categories:
        children_of[row["parent_id"]].append(row)

    def node(row: RowMapping) -> CategoryNode:
        return CategoryNode(
            id=CategoryId(row["id"]),
            slug=row["slug"],
            name=row["name"],
            icon=row["icon"],
            price_hints=row["price_hint"],
            tags=tuple(tags_of[row["id"]]),
            children=tuple(node(child) for child in children_of[row["id"]]),
        )

    return [node(row) for row in children_of[None]]


def _summary(row: RowMapping) -> CategorySummary:
    return CategorySummary(
        id=CategoryId(row["id"]),
        parent_id=CategoryId(row["parent_id"]) if row["parent_id"] is not None else None,
        slug=row["slug"],
        name=row["name"],
        path=tuple(CategoryId(i) for i in row["path"]),
        risk_level=RiskLevel(row["risk_level"]),
        is_active=row["is_active"],
        jobs_enabled=row["jobs_enabled"],
        max_responses=row["max_responses"],
    )
