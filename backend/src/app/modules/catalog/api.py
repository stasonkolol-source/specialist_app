"""Контракт модуля catalog для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из catalog только этот файл: jobs и specialists проверяют
категорию и берут её `path` для `category_path` (фильтр «с подкатегориями» без рекурсии,
§7.5), moderation — `risk_level`, jobs — `jobs_enabled` и `max_responses`.
"""

from collections.abc import Collection
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol

from app.platform.kernel.ids import CategoryId
from app.platform.kernel.localized import LocalizedText


class RiskLevel(IntEnum):
    """Риск категории (§7.5): порядок значим — чем выше, тем строже модерация."""

    NORMAL = 0
    PREMODERATION = 1
    """Профили и заявки категории проходят обязательную проверку."""
    FORBIDDEN = 2
    """Стоп-категория: не показывается, профили и заявки в ней запрещены."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CategorySummary:
    id: CategoryId
    parent_id: CategoryId | None
    slug: str
    name: LocalizedText
    path: tuple[CategoryId, ...]
    """Предки и сама категория, от корня: (1, 12, 57)."""
    risk_level: RiskLevel
    is_active: bool
    jobs_enabled: bool
    """Можно ли публиковать заявки в категории."""
    max_responses: int
    """Лимит откликов на заявку в категории."""


class CatalogApi(Protocol):
    async def category(self, category_id: CategoryId) -> CategorySummary | None:
        """Категория по id, в том числе выключенная: решение за вызывающим."""
        ...

    async def categories(self, category_ids: Collection[CategoryId]) -> list[CategorySummary]:
        """Несколько категорий одним запросом (категории профиля); порядок — по path."""
        ...
