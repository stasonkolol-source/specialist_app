"""Реализация PricingApi (ADR-0020 §6): сводка видимого прайса каждого профиля для поиска,
прайс для карточки S08–S09 и текстом для модерации профиля (B3).

Прайс правится без проверки до публикации: позиция видна сразу, а модерация проверяет её после
(PriceListChanged). Поэтому у автора с уровнем доверия ≤ 1 контакты в тексте позиций на карточке
скрыты маской (`masked`: автора знает вызывающий — лишнего чтения нет)."""

from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import replace
from uuid import UUID

from app.modules.pricing.api import PricingApi, PublicService, SearchPrices
from app.modules.pricing.application.ports import ServiceRepository
from app.modules.pricing.domain.service import PriceType, Service
from app.platform.kernel.ids import CategoryId
from app.platform.text.contact_masking import mask_contacts

HOUR = "hour"
"""Единица почасовой цены: у такой позиции своей единицы нет, «за час» — сам тип."""


class PricingFacade(PricingApi):
    def __init__(self, services: ServiceRepository) -> None:
        self._services = services

    async def search_prices(self, profile_ids: Collection[UUID]) -> dict[UUID, SearchPrices]:
        grouped: defaultdict[UUID, list[Service]] = defaultdict(list)
        for service in await self._services.visible(profile_ids):
            grouped[service.profile_id].append(service)
        return {profile_id: _summary(items) for profile_id, items in grouped.items()}

    async def public_services(
        self, profile_id: UUID, *, masked: bool = False
    ) -> list[PublicService]:
        services = [_public(service) for service in await self._services.visible([profile_id])]
        return [_masked(service) for service in services] if masked else services

    async def text_for_review(self, profile_id: UUID) -> str:
        return "\n".join(
            part
            for service in await self._services.visible([profile_id])
            for part in (service.title, service.description, service.unit)
            if part
        )


def _summary(services: Iterable[Service]) -> SearchPrices:
    """Сводка по позициям в порядке S35: при равных ценах единица — у позиции выше по прайсу."""
    titles: list[str] = []
    lowest: int | None = None
    lowest_unit: str | None = None
    by_category: dict[CategoryId, int] = {}
    unit_by_category: dict[CategoryId, str | None] = {}
    for service in services:
        titles.append(service.title)
        price = service.price_min
        if service.price_type is PriceType.NEGOTIABLE or price is None:
            continue
        unit = _unit(service)
        if lowest is None or price < lowest:
            lowest, lowest_unit = price, unit
        category = service.category_id
        if category is not None:
            known = by_category.get(category)
            if known is None or price < known:
                by_category[category], unit_by_category[category] = price, unit
    return SearchPrices(
        titles=tuple(titles),
        price_from=lowest,
        price_from_unit=lowest_unit,
        by_category=by_category,
        unit_by_category=unit_by_category,
    )


def _unit(service: Service) -> str | None:
    return HOUR if service.price_type is PriceType.HOURLY else service.unit


def _public(service: Service) -> PublicService:
    return PublicService(
        id=service.id,
        title=service.title,
        description=service.description,
        category_id=service.category_id,
        price_type=service.price_type.value,
        price_min=service.price_min,
        price_max=service.price_max,
        unit=service.unit,
        duration_min=service.duration_min,
    )


def _masked(service: PublicService) -> PublicService:
    return replace(
        service,
        title=mask_contacts(service.title),
        description=mask_contacts(service.description) if service.description else None,
        unit=mask_contacts(service.unit) if service.unit else None,
    )
