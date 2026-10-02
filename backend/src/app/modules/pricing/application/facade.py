"""Реализация PricingApi для поиска (ADR-0020 §6): сводка видимого прайса каждого профиля."""

from collections import defaultdict
from collections.abc import Collection, Iterable
from uuid import UUID

from app.modules.pricing.api import PricingApi, SearchPrices
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
