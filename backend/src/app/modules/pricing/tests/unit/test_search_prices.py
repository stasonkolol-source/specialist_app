"""Прайс для выдачи (DEVELOPMENT_PLAN 4.1): цена «от» с единицей той же позиции — по всему
прайсу и по группам; карточка S05 пишет «от 1 000 RSD/час»."""

from collections.abc import Collection
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from app.modules.pricing.api import SearchPrices
from app.modules.pricing.application.facade import PricingFacade
from app.modules.pricing.application.ports import ServiceRepository
from app.modules.pricing.domain.service import PriceType, Service
from app.platform.kernel.ids import CategoryId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
PROFILE = new_id()
REPAIR, ELECTRIC = CategoryId(1), CategoryId(2)


class Visible:
    """Только чтение фасада: видимые позиции в порядке S35."""

    def __init__(self, *services: Service) -> None:
        self.services = list(services)

    async def visible(self, profile_ids: Collection[UUID]) -> list[Service]:
        return [service for service in self.services if service.profile_id in profile_ids]


def item(
    title: str,
    price_type: PriceType,
    price: int | None = None,
    *,
    category: CategoryId | None = None,
    unit: str | None = None,
) -> Service:
    return Service.add(
        profile_id=PROFILE,
        title=title,
        price_type=price_type,
        now=NOW,
        position=0,
        price_min=price,
        category_id=category,
        unit=unit,
    )


async def prices_of(*services: Service) -> SearchPrices:
    facade = PricingFacade(cast(ServiceRepository, Visible(*services)))
    return (await facade.search_prices([PROFILE]))[PROFILE]


async def test_price_from_comes_with_the_unit_of_its_item() -> None:
    prices = await prices_of(
        item("Выезд и диагностика", PriceType.FIXED, 200_000, category=ELECTRIC, unit="visit"),
        item("Мастер на час", PriceType.HOURLY, 100_000, category=REPAIR),
        item("Розетка", PriceType.PER_UNIT, 100_000, category=ELECTRIC, unit="item"),
        item("Сложный случай", PriceType.NEGOTIABLE),
    )

    # у почасовой своей единицы нет — «час»; при равных ценах — позиция выше по прайсу
    assert (prices.price_from, prices.price_from_unit) == (100_000, "hour")
    assert prices.by_category == {ELECTRIC: 100_000, REPAIR: 100_000}
    assert prices.unit_by_category == {ELECTRIC: "item", REPAIR: "hour"}


async def test_price_for_the_whole_work_has_no_unit() -> None:
    prices = await prices_of(item("Сборка шкафа", PriceType.FROM, 300_000, category=REPAIR))

    assert (prices.price_from, prices.price_from_unit) == (300_000, None)
    assert prices.unit_by_category == {REPAIR: None}
