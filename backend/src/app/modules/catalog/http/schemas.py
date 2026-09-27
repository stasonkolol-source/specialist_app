"""Схемы HTTP catalog: названия — одной строкой на языке Accept-Language (ARCHITECTURE §8.1).

Наружу — только то, что нужно экранам: дерево, иконки, теги и ориентир цены. Настройки
модерации (`risk_level`, `jobs_enabled`, `max_responses`) остаются внутри: их читают
модули через фасад, а запрещённые категории в дерево не попадают вовсе.
"""

from pydantic import BaseModel

from app.modules.catalog.application.dto import CategoryView
from app.modules.catalog.domain.category import PriceUnit
from app.platform.http.money import MoneyOut
from app.platform.kernel.localized import Locale


class PriceHintOut(BaseModel):
    """«Обычно за это платят 1 000–2 400 RSD за час» (§7.7)."""

    min: MoneyOut
    max: MoneyOut
    unit: PriceUnit


class TagOut(BaseModel):
    id: int
    slug: str
    name: str


class CategoryOut(BaseModel):
    id: int
    slug: str
    name: str
    icon: str | None
    price_hint: PriceHintOut | None
    """Ориентир в городе из `?city=`; null — город не передан или ориентира в нём нет."""
    tags: list[TagOut]
    children: list[CategoryOut]

    @classmethod
    def of(cls, node: CategoryView, locale: Locale, city: str | None) -> CategoryOut:
        hint = node.price_hints.get(city) if city is not None else None
        price_hint = (
            PriceHintOut(min=MoneyOut.of(hint.min), max=MoneyOut.of(hint.max), unit=hint.unit)
            if hint is not None
            else None
        )
        return cls(
            id=node.id,
            slug=node.slug,
            name=node.name.get(locale),
            icon=node.icon,
            price_hint=price_hint,
            tags=[TagOut(id=t.id, slug=t.slug, name=t.name.get(locale)) for t in node.tags],
            children=[cls.of(child, locale, city) for child in node.children],
        )
