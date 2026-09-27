"""Ориентир цены категории: пара, только RSD, корректный диапазон (ARCHITECTURE §7.1, §7.7)."""

import pytest

from app.modules.catalog.domain.category import PriceHint, PriceUnit
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.money import Currency, Money

pytestmark = pytest.mark.unit


def test_price_hint_from_whole_dinars_is_stored_in_para() -> None:
    hint = PriceHint.from_rsd(1000, 2400, PriceUnit.HOUR)
    assert hint.min == Money(100_000)
    assert hint.max == Money(240_000)
    assert hint.min.major == 1000
    assert hint.unit is PriceUnit.HOUR


def test_price_hint_allows_a_single_price() -> None:
    assert PriceHint.from_rsd(1500, 1500, PriceUnit.LESSON).max == Money.rsd(1500)


@pytest.mark.parametrize(("low", "high"), [(0, 100), (500, 400), (-1, 10)])
def test_price_hint_range_must_be_positive_and_ordered(low: int, high: int) -> None:
    with pytest.raises(DomainValidationError) as error:
        PriceHint.from_rsd(low, high, PriceUnit.WORK)
    assert error.value.params == {"field": "price_hint", "reason": "range"}


def test_price_hint_is_rsd_only() -> None:
    with pytest.raises(DomainValidationError) as error:
        PriceHint(min=Money(100, Currency.XTR), max=Money(200, Currency.XTR), unit=PriceUnit.WORK)
    assert error.value.params["reason"] == "rsd_only"
