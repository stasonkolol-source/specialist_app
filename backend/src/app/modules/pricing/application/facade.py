"""Реализация PricingApi для поиска (ADR-0020 §6): сводка видимого прайса каждого профиля."""

from collections import defaultdict
from collections.abc import Collection, Iterable
from uuid import UUID

from app.modules.pricing.api import PricingApi, PublicService, SearchPrices
from app.modules.pricing.application.ports import ServiceRepository
from app.modules.pricing.domain.service import PriceType, Service
from app.platform.kernel.ids import CategoryId


class PricingFacade(PricingApi):
    def __init__(self, services: ServiceRepository) -> None:
        self._services = services

    async def search_prices(self, profile_ids: Collection[UUID]) -> dict[UUID, SearchPrices]:
        grouped: defaultdict[UUID, list[Service]] = defaultdict(list)
        for service in await self._services.visible(profile_ids):
            grouped[service.profile_id].append(service)
        return {profile_id: _summary(items) for profile_id, items in grouped.items()}

    async def public_services(self, profile_id: UUID) -> list[PublicService]:
        return [_public(service) for service in await self._services.visible([profile_id])]


def _summary(services: Iterable[Service]) -> SearchPrices:
    titles: list[str] = []
    lowest: int | None = None
    by_category: dict[CategoryId, int] = {}
    for service in services:
        titles.append(service.title)
        price = service.price_min
        if service.price_type is PriceType.NEGOTIABLE or price is None:
            continue
        lowest = price if lowest is None else min(lowest, price)
        if service.category_id is not None:
            known = by_category.get(service.category_id)
            by_category[service.category_id] = price if known is None else min(known, price)
    return SearchPrices(titles=tuple(titles), price_from=lowest, by_category=by_category)


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
