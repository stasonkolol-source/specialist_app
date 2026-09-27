"""Деньги (ARCHITECTURE §7.1): целое число минимальных единиц + валюта, без float.

Цены, бюджеты и отклики — только в RSD (ст. 34 Zakon o deviznom poslovanju).
Минимальная единица RSD — пара, 1 динар = 100 пара. XTR (Telegram Stars) — только для
оплаты цифрового в billing (v1); цены услуг и бюджеты в XTR не бывают (CHECK в БД).
"""

from dataclasses import dataclass
from enum import StrEnum
from functools import total_ordering
from typing import Self

from app.platform.kernel.errors import DomainValidationError


class Currency(StrEnum):
    RSD = "RSD"
    XTR = "XTR"


MINOR_UNITS = {Currency.RSD: 100, Currency.XTR: 1}


class CurrencyMismatchError(DomainValidationError):
    code = "currency_mismatch"


@total_ordering
@dataclass(frozen=True, slots=True)
class Money:
    amount: int
    """Минимальные единицы валюты (для RSD — пара)."""
    currency: Currency = Currency.RSD

    def __post_init__(self) -> None:
        if isinstance(self.amount, bool) or not isinstance(self.amount, int):
            raise TypeError("Money.amount must be int (minor units), not float or bool")
        if not isinstance(self.currency, Currency):
            raise DomainValidationError(field="currency", value=str(self.currency))

    @classmethod
    def rsd(cls, dinars: int) -> Self:
        """Сумма в целых динарах: Money.rsd(5000) — 5 000 RSD."""
        return cls(dinars * MINOR_UNITS[Currency.RSD], Currency.RSD)

    @classmethod
    def zero(cls, currency: Currency = Currency.RSD) -> Self:
        return cls(0, currency)

    @property
    def major(self) -> int:
        """Целая часть в основных единицах (динарах)."""
        return self.amount // MINOR_UNITS[self.currency]

    def _check(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"cannot combine Money with {type(other).__name__}")
        if other.currency is not self.currency:
            raise CurrencyMismatchError(left=self.currency.value, right=other.currency.value)

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: int) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, int):
            raise TypeError("Money can be multiplied only by int")
        return Money(self.amount * factor, self.currency)

    __rmul__ = __mul__

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount < other.amount

    def is_negative(self) -> bool:
        return self.amount < 0
