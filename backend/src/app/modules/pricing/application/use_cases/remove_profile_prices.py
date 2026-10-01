"""Прайс удалённого профиля (подписчик ProfileDeleted; ARCHITECTURE §7.10): аккаунт удалён —
все позиции удалены. Повтор задачи ничего не меняет: удалённых позиций уже нет в выборке."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.pricing.application.ports import ServiceRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoveProfilePricesCommand:
    profile_id: UUID


class RemoveProfilePrices:
    def __init__(self, uow: UnitOfWork, services: ServiceRepository, clock: Clock) -> None:
        self._uow, self._services, self._clock = uow, services, clock

    async def __call__(self, cmd: RemoveProfilePricesCommand) -> int:
        """Сколько позиций удалено."""
        now = self._clock.now()
        async with self._uow:
            services = await self._services.list_for_update(cmd.profile_id)
            for service in services:
                await self._services.delete(service, now=now)
        return len(services)
