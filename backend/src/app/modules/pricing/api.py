"""Контракт модуля pricing для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из pricing только этот файл.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.platform.kernel.ids import CategoryId


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchPrices:
    """Прайс профиля для выдачи поиска (4.1): что искать по прайсу и с какой цены «от».

    Скрытые позиции сюда не входят. «Договорная» даёт название, но не цену.
    """

    titles: tuple[str, ...] = ()
    """Названия видимых позиций по порядку — документ поиска (вес C)."""
    price_from: int | None = None
    """Самая низкая цена среди видимых позиций с ценой, пара; None — цен нет."""
    by_category: Mapping[CategoryId, int] = field(default_factory=dict)
    """Самая низкая цена по группе позиции (категории S35), пара."""


class PricingApi(Protocol):
    async def search_prices(self, profile_ids: Collection[UUID]) -> dict[UUID, SearchPrices]:
        """Прайсы профилей для поиска; профиль без видимых позиций в ответ не попадает."""
        ...
