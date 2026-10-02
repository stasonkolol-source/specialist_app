"""Чтение справочника catalog (ADR-0020 §5): публичное дерево и категории для фасада."""

import re
from collections import defaultdict
from collections.abc import Collection, Sequence
from typing import Any, Final

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.engine import RowMapping

from app.modules.catalog.api import CategorySummary, RiskLevel, SearchTerm, TermMatch
from app.modules.catalog.application.dto import CategoryView, TagView
from app.modules.catalog.infrastructure.models import CategoryRow, SearchTermRow, TagRow
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import CategoryId, TagId
from app.platform.kernel.localized import Locale

_CATEGORIES = CategoryRow.__table__.c
_TERMS = SearchTermRow.__table__.c
MIN_PREFIX: Final = 3
"""Префикс короче — слишком общий: «эл» начинает и «электрик», и «элемент»."""
MAX_MATCHED: Final = 10
"""Категорий из одного слова запроса — с запасом: «ремонт» узнаётся в нескольких."""
_CYRILLIC = re.compile("[\u0400-\u04ff]")
_CYRILLIC_LANGS: Final = (Locale.RU, Locale.SR_CYRL)
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
    async def tree(self) -> list[CategoryView]:
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

    async def search_terms(
        self, category_ids: Collection[CategoryId]
    ) -> dict[CategoryId, tuple[SearchTerm, ...]]:
        t = SearchTermRow.__table__.c
        rows = await self._fetch(
            select(t.category_id, t.lang, t.term)
            .where(t.category_id.in_(list(category_ids)))
            .order_by(t.category_id, t.lang, t.term)
        )
        terms: defaultdict[CategoryId, list[SearchTerm]] = defaultdict(list)
        for row in rows:
            terms[CategoryId(row["category_id"])].append(
                SearchTerm(lang=row["lang"], term=row["term"])
            )
        return {category_id: tuple(found) for category_id, found in terms.items()}

    async def match_query(self, text: str) -> TermMatch | None:
        norm = func.platform.search_norm(text)
        exact = _TERMS.norm == norm
        rows = await self._fetch(
            _visible_terms(exact.label("exact"))
            .where(
                exact
                | (
                    (func.length(norm) >= MIN_PREFIX)
                    & _TERMS.norm.startswith(norm, autoescape=False)
                )
            )
            .order_by(exact.desc(), _TERMS.weight.desc(), func.length(_TERMS.norm), _TERMS.id)
        )
        if not rows:
            return None
        best = [row for row in rows if row["exact"] == rows[0]["exact"]]
        ids = list(dict.fromkeys(CategoryId(row["category_id"]) for row in best))
        return TermMatch(
            category_ids=tuple(ids[:MAX_MATCHED]), term=best[0]["term"], exact=best[0]["exact"]
        )

    async def similar_term(self, text: str) -> TermMatch | None:
        norm = func.platform.search_norm(text)
        row = await self._fetch_one(
            _visible_terms()
            .where(_TERMS.norm.op("%")(norm))
            .order_by(
                _TERMS.norm.op("<->")(norm),
                # подсказка — тем же алфавитом, каким набран запрос
                _TERMS.lang.in_(_CYRILLIC_LANGS) != bool(_CYRILLIC.search(text)),
                _TERMS.weight.desc(),
                _TERMS.id,
            )
            .limit(1)
        )
        if row is None:
            return None
        return TermMatch(
            category_ids=(CategoryId(row["category_id"]),), term=row["term"], exact=False
        )


def _visible_terms(*extra: ColumnElement[Any]) -> Select[Any]:
    """Слова словаря активных и не запрещённых категорий (как в публичном дереве)."""
    c = _CATEGORIES
    return (
        select(_TERMS.category_id, _TERMS.term, *extra)
        .join(CategoryRow.__table__, c.id == _TERMS.category_id)
        .where(c.is_active, c.risk_level < int(RiskLevel.FORBIDDEN))
    )


def _tree(categories: Sequence[RowMapping], tags: Sequence[RowMapping]) -> list[CategoryView]:
    """Дерево из плоских строк: потомки выключенной категории в него не попадают."""
    tags_of: defaultdict[int, list[TagView]] = defaultdict(list)
    for tag in tags:
        tags_of[tag["category_id"]].append(
            TagView(id=TagId(tag["id"]), slug=tag["slug"], name=tag["name"])
        )
    children_of: defaultdict[int | None, list[RowMapping]] = defaultdict(list)
    for row in categories:
        children_of[row["parent_id"]].append(row)

    def node(row: RowMapping) -> CategoryView:
        return CategoryView(
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
