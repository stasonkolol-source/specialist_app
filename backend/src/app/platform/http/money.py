"""Деньги в API (ARCHITECTURE §8.1): `{"amount": 500000, "currency": "RSD"}`.

Сумма — в минимальных единицах валюты (для RSD — пара), форматирует клиент.
"""

from pydantic import BaseModel

from app.platform.kernel.money import Currency, Money


class MoneyOut(BaseModel):
    amount: int
    """Минимальные единицы валюты: 1 RSD = 100 пара."""
    currency: Currency

    @classmethod
    def of(cls, money: Money) -> MoneyOut:
        return cls(amount=money.amount, currency=money.currency)
