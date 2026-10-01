"""Позиция прайса (ARCHITECTURE §7.3 `pricing.services`, DEVELOPMENT_PLAN 2.8b).

Цена — только RSD, в минимальных единицах (пара). Типы: фиксированная, «от», диапазон, за час,
за единицу (`unit`: точка, м², урок…), договорная. S36 в MVP показывает фикс, «от» и за час.
"""

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, NewType
from uuid import UUID

from app.modules.pricing.errors import InvalidServiceError
from app.platform.kernel.aggregate import AggregateRoot
from app.platform.kernel.ids import CategoryId, new_id

ServiceId = NewType("ServiceId", UUID)

MAX_TITLE: Final = 120
MAX_DESCRIPTION: Final = 1000
MAX_UNIT: Final = 32
MAX_ITEMS: Final = 50
"""Позиций в прайсе **[Допущение]**: в S35 прайс больше списка категорий профиля не бывает."""
MAX_PRICE: Final = 1_000_000_000 * 100
"""Миллиард динаров в пара: защита от опечатки в нулях."""
MAX_DURATION_MIN: Final = 24 * 60 * 30


class PriceType(StrEnum):
    FIXED = "fixed"
    FROM = "from"
    RANGE = "range"
    HOURLY = "hourly"
    PER_UNIT = "per_unit"
    NEGOTIABLE = "negotiable"


@dataclass(eq=False, kw_only=True)
class Service(AggregateRoot):
    id: ServiceId
    profile_id: UUID
    title: str
    price_type: PriceType
    created_at: datetime
    description: str | None = None
    category_id: CategoryId | None = None
    """Группа в S35 (категория профиля)."""
    price_min: int | None = None
    """Пара; у договорной — None."""
    price_max: int | None = None
    unit: str | None = None
    duration_min: int | None = None
    position: int = 0
    is_active: bool = True
    """False — «Скрыта» в S35: в профиле не показывается."""

    @classmethod
    def add(
        cls,
        *,
        profile_id: UUID,
        title: str,
        price_type: PriceType,
        now: datetime,
        position: int,
        description: str | None = None,
        category_id: CategoryId | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        unit: str | None = None,
        duration_min: int | None = None,
    ) -> Service:
        service = cls(
            id=ServiceId(new_id()),
            profile_id=profile_id,
            title=_title(title),
            price_type=price_type,
            created_at=now,
            position=position,
        )
        service.change(
            description=description,
            category_id=category_id,
            price_min=price_min,
            price_max=price_max,
            unit=unit,
            duration_min=duration_min,
        )
        return service

    def change(
        self,
        *,
        title: str | None = None,
        price_type: PriceType | None = None,
        description: str | None = None,
        category_id: CategoryId | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        unit: str | None = None,
        duration_min: int | None = None,
        is_active: bool | None = None,
        clear: frozenset[str] = frozenset(),
    ) -> None:
        """Изменить переданные поля; `clear` — поля, которые обнулить (описание, максимум…)."""
        if title is not None:
            self.title = _title(title)
        if price_type is not None:
            self.price_type = price_type
        if description is not None or "description" in clear:
            self.description = _text(description or "", MAX_DESCRIPTION, "description")
        if category_id is not None or "category_id" in clear:
            self.category_id = category_id
        for name, value in (("price_min", price_min), ("price_max", price_max)):
            if value is not None or name in clear:
                if value is not None and not 0 <= value <= MAX_PRICE:
                    raise InvalidServiceError(field=name)
                setattr(self, name, value)
        if unit is not None or "unit" in clear:
            self.unit = _text(unit or "", MAX_UNIT, "unit")
        if duration_min is not None or "duration_min" in clear:
            if duration_min is not None and not 1 <= duration_min <= MAX_DURATION_MIN:
                raise InvalidServiceError(field="duration_min")
            self.duration_min = duration_min
        if is_active is not None:
            self.is_active = is_active
        self._validate_price()

    def _validate_price(self) -> None:
        if self.price_type is PriceType.NEGOTIABLE:
            self.price_min = self.price_max = None
            return
        if self.price_min is None:
            raise InvalidServiceError(field="price_min")
        if self.price_type is PriceType.RANGE:
            if self.price_max is None or self.price_max < self.price_min:
                raise InvalidServiceError(field="price_max")
        else:
            self.price_max = None
        if self.price_type is PriceType.PER_UNIT and not self.unit:
            raise InvalidServiceError(field="unit")


def _title(value: str) -> str:
    title = " ".join(_clean(value).split())
    if not title or len(title) > MAX_TITLE:
        raise InvalidServiceError(field="title")
    return title


def _text(value: str, limit: int, field: str) -> str | None:
    text = _clean(value).strip()
    if len(text) > limit:
        raise InvalidServiceError(field=field)
    return text or None


def _clean(value: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFC", value)
        if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf"}
    )
