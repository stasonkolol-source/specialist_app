"""Прайс для specialists (порт `specialists.api.PriceList`): pricing выше по DAG, поэтому
specialists спрашивает о прайсе через свой порт, а реализует его pricing."""

from uuid import UUID

from app.modules.pricing.application.ports import ServiceRepository
from app.modules.specialists.api import PriceList, PriceSummary


class ServicesPriceList(PriceList):
    def __init__(self, services: ServiceRepository) -> None:
        self._services = services

    async def has_items(self, profile_id: UUID) -> bool:
        return await self._services.has_active(profile_id)

    async def summary(self, profile_id: UUID) -> PriceSummary:
        return await self._services.summary(profile_id)
