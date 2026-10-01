"""Позиция прайса (DEVELOPMENT_PLAN 2.8b): типы цены и проверки."""

from datetime import UTC, datetime

import pytest

from app.modules.pricing.domain.service import MAX_PRICE, PriceType, Service
from app.modules.pricing.errors import InvalidServiceError
from app.platform.kernel.ids import new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def service(price_type: PriceType = PriceType.FIXED, **fields: object) -> Service:
    return Service.add(
        profile_id=new_id(),
        title="  Замена  розетки ",
        price_type=price_type,
        now=NOW,
        position=0,
        **fields,  # type: ignore[arg-type]
    )


def test_fixed_price_in_para() -> None:
    item = service(price_min=150_000)

    assert (item.title, item.price_min, item.price_max) == ("Замена розетки", 150_000, None)


@pytest.mark.parametrize(
    ("price_type", "fields", "field"),
    [
        (PriceType.FIXED, {}, "price_min"),  # цена обязательна
        (PriceType.RANGE, {"price_min": 1000}, "price_max"),
        (PriceType.RANGE, {"price_min": 2000, "price_max": 1000}, "price_max"),
        (PriceType.PER_UNIT, {"price_min": 1000}, "unit"),
        (PriceType.FIXED, {"price_min": MAX_PRICE + 1}, "price_min"),
        (PriceType.HOURLY, {"price_min": 100, "duration_min": 0}, "duration_min"),
    ],
)
def test_price_rules(price_type: PriceType, fields: dict[str, object], field: str) -> None:
    with pytest.raises(InvalidServiceError) as invalid:
        service(price_type, **fields)
    assert invalid.value.params == {"field": field}


def test_negotiable_has_no_price_and_range_keeps_both() -> None:
    assert service(PriceType.NEGOTIABLE, price_min=500).price_min is None
    item = service(PriceType.RANGE, price_min=1000, price_max=3000)
    assert (item.price_min, item.price_max) == (1000, 3000)


def test_change_and_clear() -> None:
    item = service(price_min=1000, description="Работа и материалы")

    item.change(price_type=PriceType.FROM, is_active=False, clear=frozenset({"description"}))

    assert (item.price_type, item.is_active, item.description) == (PriceType.FROM, False, None)
    with pytest.raises(InvalidServiceError):
        item.change(title="   ")
