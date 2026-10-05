"""Удалить позицию прайса (DELETE /me/profile/services/{id}); порядок остальных сжимается."""

from dataclasses import dataclass

from app.modules.identity.api import Action, IdentityApi
from app.modules.pricing.application.ports import ServiceRepository
from app.modules.pricing.application.profile import price_list_changed, profile_id_of
from app.modules.pricing.domain.service import ServiceId
from app.modules.pricing.errors import ServiceNotFoundError
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoveServiceCommand:
    actor_id: UserId
    service_id: ServiceId


class RemoveService:
    def __init__(
        self,
        uow: UnitOfWork,
        services: ServiceRepository,
        specialists: SpecialistsApi,
        clock: Clock,
        identity: IdentityApi,
    ) -> None:
        self._uow, self._services, self._specialists, self._clock = (
            uow,
            services,
            specialists,
            clock,
        )
        self._identity = identity

    async def __call__(self, cmd: RemoveServiceCommand) -> None:
        # санкция на публикацию и галочка S02c — как у создания профиля (SEC-01)
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        profile_id = await profile_id_of(self._specialists, cmd.actor_id)
        async with self._uow:
            services = await self._services.list_for_update(profile_id)
            target = next((s for s in services if s.id == cmd.service_id), None)
            if target is None:
                raise ServiceNotFoundError(service_id=cmd.service_id)
            await self._services.delete(target, now=self._clock.now())
            for position, service in enumerate(s for s in services if s.id != cmd.service_id):
                if service.position != position:
                    service.position = position
                    await self._services.save(service)
            price_list_changed(self._uow, profile_id, cmd.actor_id, self._clock)
