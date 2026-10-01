"""Порядок прайса (PUT /me/profile/services/order; S35 — перетаскиванием): список id целиком."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.pricing.application.ports import ServiceRepository
from app.modules.pricing.application.profile import price_list_changed, profile_id_of
from app.modules.pricing.domain.service import Service, ServiceId
from app.modules.pricing.errors import InvalidServiceError
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ReorderServicesCommand:
    actor_id: UserId
    service_ids: Sequence[ServiceId]
    """Все позиции прайса в новом порядке."""


class ReorderServices:
    def __init__(
        self,
        uow: UnitOfWork,
        services: ServiceRepository,
        specialists: SpecialistsApi,
        clock: Clock,
    ) -> None:
        self._uow, self._services, self._specialists, self._clock = (
            uow,
            services,
            specialists,
            clock,
        )

    async def __call__(self, cmd: ReorderServicesCommand) -> list[Service]:
        profile_id = await profile_id_of(self._specialists, cmd.actor_id)
        async with self._uow:
            services = {s.id: s for s in await self._services.list_for_update(profile_id)}
            if len(cmd.service_ids) != len(set(cmd.service_ids)) or set(cmd.service_ids) != set(
                services
            ):
                raise InvalidServiceError(field="service_ids")
            ordered = [services[service_id] for service_id in cmd.service_ids]
            for position, service in enumerate(ordered):
                if service.position != position:
                    service.position = position
                    await self._services.save(service)
            price_list_changed(self._uow, profile_id, cmd.actor_id, self._clock)
        return ordered
