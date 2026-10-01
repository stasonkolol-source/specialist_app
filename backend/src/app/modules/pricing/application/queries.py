"""Прайс своего профиля для кабинета (S35): позиции по порядку, скрытые — тоже."""

from app.modules.pricing.application.ports import ServiceRepository
from app.modules.pricing.application.profile import profile_id_of
from app.modules.pricing.domain.service import Service
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


class PriceListQueries:
    def __init__(
        self, uow: UnitOfWork, services: ServiceRepository, specialists: SpecialistsApi
    ) -> None:
        self._uow, self._services, self._specialists = uow, services, specialists

    async def own(self, user_id: UserId) -> list[Service]:
        profile_id = await profile_id_of(self._specialists, user_id)
        async with self._uow:
            return await self._services.list_for_update(profile_id)
