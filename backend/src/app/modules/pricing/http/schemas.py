"""Схемы HTTP прайса `/me/profile/services*` (ARCHITECTURE §8.5)."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.pricing.domain.service import (
    MAX_DESCRIPTION,
    MAX_DURATION_MIN,
    MAX_PRICE,
    MAX_TITLE,
    MAX_UNIT,
    PriceType,
    Service,
)
from app.platform.http.money import MoneyOut
from app.platform.kernel.money import Currency, Money

INT4_MAX = 2**31 - 1


class ServiceIn(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE)
    price_type: PriceType
    price_min: int | None = Field(default=None, ge=0, le=MAX_PRICE)
    """Пара (1 RSD = 100 пара); у договорной не нужна."""
    price_max: int | None = Field(default=None, ge=0, le=MAX_PRICE)
    """Только у диапазона."""
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    category_id: int | None = Field(default=None, ge=1, le=INT4_MAX)
    unit: str | None = Field(default=None, max_length=MAX_UNIT)
    duration_min: int | None = Field(default=None, ge=1, le=MAX_DURATION_MIN)


CLEARABLE = Literal["description", "category_id", "price_max", "unit", "duration_min"]


class ServiceUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE)
    price_type: PriceType | None = None
    price_min: int | None = Field(default=None, ge=0, le=MAX_PRICE)
    price_max: int | None = Field(default=None, ge=0, le=MAX_PRICE)
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION)
    category_id: int | None = Field(default=None, ge=1, le=INT4_MAX)
    unit: str | None = Field(default=None, max_length=MAX_UNIT)
    duration_min: int | None = Field(default=None, ge=1, le=MAX_DURATION_MIN)
    is_active: bool | None = None
    """false — «Скрыта»: в профиле позиция не показывается."""
    clear: list[CLEARABLE] = Field(default_factory=list, max_length=5)
    """Поля, которые обнулить."""


class ServicesOrderIn(BaseModel):
    service_ids: list[UUID] = Field(min_length=1, max_length=100)


class ServiceOut(BaseModel):
    id: UUID
    title: str
    description: str | None
    category_id: int | None
    price_type: PriceType
    price_min: MoneyOut | None
    price_max: MoneyOut | None
    unit: str | None
    duration_min: int | None
    position: int
    is_active: bool

    @classmethod
    def of(cls, service: Service) -> ServiceOut:
        return cls(
            id=service.id,
            title=service.title,
            description=service.description,
            category_id=service.category_id,
            price_type=service.price_type,
            price_min=_money(service.price_min),
            price_max=_money(service.price_max),
            unit=service.unit,
            duration_min=service.duration_min,
            position=service.position,
            is_active=service.is_active,
        )


class ServicesOut(BaseModel):
    items: list[ServiceOut]


def _money(amount: int | None) -> MoneyOut | None:
    return MoneyOut.of(Money(amount, Currency.RSD)) if amount is not None else None
