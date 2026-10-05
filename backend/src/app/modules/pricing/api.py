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
    price_from_unit: str | None = None
    """Единица этой цены — «от 1 000 RSD/час» в карточке выдачи: `hour` у почасовой, иначе единица
    позиции; None — за работу целиком. При равных ценах — у позиции выше по прайсу."""
    by_category: Mapping[CategoryId, int] = field(default_factory=dict)
    """Самая низкая цена по группе позиции (категории S35), пара."""
    unit_by_category: Mapping[CategoryId, str | None] = field(default_factory=dict)
    """Единица цены `by_category` — по тем же правилам, что `price_from_unit`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicService:
    """Позиция прайса для клиента (карточка S08, прайс S09): видимая, в порядке S35."""

    id: UUID
    title: str
    description: str | None
    category_id: CategoryId | None
    price_type: str
    """fixed | from | range | hourly | per_unit | negotiable."""
    price_min: int | None
    """Пара."""
    price_max: int | None
    unit: str | None
    duration_min: int | None


class PricingApi(Protocol):
    async def search_prices(self, profile_ids: Collection[UUID]) -> dict[UUID, SearchPrices]:
        """Прайсы профилей для поиска; профиль без видимых позиций в ответ не попадает."""
        ...

    async def public_services(self, profile_id: UUID) -> list[PublicService]:
        """Видимые позиции прайса профиля в порядке S35: «Скрытые» и удалённые — нет."""
        ...
