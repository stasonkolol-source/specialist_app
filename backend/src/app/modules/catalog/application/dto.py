"""Read-DTO и данные импорта справочника catalog (ADR-0020 §3)."""

from collections.abc import Mapping
from dataclasses import dataclass

from app.modules.catalog.api import RiskLevel
from app.modules.catalog.domain.category import PriceHint
from app.modules.catalog.domain.terms import SearchTerm
from app.platform.kernel.ids import CategoryId, TagId
from app.platform.kernel.localized import LocalizedText


@dataclass(frozen=True, slots=True, kw_only=True)
class TagView:
    id: TagId
    slug: str
    name: LocalizedText


@dataclass(frozen=True, slots=True, kw_only=True)
class CategoryNode:
    """Узел публичного дерева: активная и не запрещённая категория с активными тегами."""

    id: CategoryId
    slug: str
    name: LocalizedText
    icon: str | None
    price_hints: Mapping[str, PriceHint]
    """Ориентиры цены по slug города."""
    tags: tuple[TagView, ...]
    children: tuple[CategoryNode, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class TagSeed:
    slug: str
    name: LocalizedText


@dataclass(frozen=True, slots=True, kw_only=True)
class CategorySeed:
    slug: str
    name: LocalizedText
    icon: str | None
    risk_level: RiskLevel
    sort_order: int
    """Порядок среди соседей: в сидах — порядок в YAML."""
    price_hints: Mapping[str, PriceHint]
    synonyms: tuple[SearchTerm, ...]
    tags: tuple[TagSeed, ...]
    children: tuple[CategorySeed, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportResult:
    """Счётчики — по категориям; теги и словарь входят в свою категорию."""

    created: int
    updated: int
    unchanged: int
    changed: tuple[CategoryId, ...]
    """Созданные и обновлённые категории — для события CatalogChanged."""
