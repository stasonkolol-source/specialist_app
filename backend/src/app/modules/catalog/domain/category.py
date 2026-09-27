"""Категория справочника (ARCHITECTURE §7.3, §7.5, §7.7): глубина дерева и ориентир цены."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self

from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.money import Currency, Money

MAX_DEPTH: Final = 3
"""Раздел → категория → подкатегория (§7.5). В БД — CHECK ck_categories_depth."""


class PriceUnit(StrEnum):
    """За что цена в ориентире; те же значения, что у бюджета заявки (`jobs.budget_unit`, §7.3).

    `work` — за работу целиком (вызов сантехника, маникюр, переезд), `item` — за штуку.
    """

    WORK = "work"
    HOUR = "hour"
    M2 = "m2"
    VISIT = "visit"
    ITEM = "item"
    LESSON = "lesson"


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceHint:
    """Ориентир цены категории в городе (§7.7): статический диапазон MVP, только RSD.

    Суммы — в пара, как все деньги (§7.1); сиды задают их в целых динарах (`from_rsd`).
    """

    min: Money
    max: Money
    unit: PriceUnit

    def __post_init__(self) -> None:
        if self.min.currency is not Currency.RSD or self.max.currency is not Currency.RSD:
            raise DomainValidationError(field="price_hint", reason="rsd_only")
        if not Money.zero() < self.min <= self.max:
            raise DomainValidationError(field="price_hint", reason="range")

    @classmethod
    def from_rsd(cls, low: int, high: int, unit: PriceUnit) -> Self:
        """Диапазон в целых динарах: from_rsd(1000, 2400, …) — 100 000–240 000 пара."""
        return cls(min=Money.rsd(low), max=Money.rsd(high), unit=unit)
