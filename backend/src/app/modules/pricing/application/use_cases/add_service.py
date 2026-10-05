"""Добавить позицию прайса (POST /me/profile/services; S32c «Первая позиция прайса», S36)."""

from dataclasses import dataclass

from app.modules.identity.api import Action, IdentityApi
from app.modules.pricing.application.ports import ServiceRepository
from app.modules.pricing.application.profile import price_list_changed, profile_id_of
from app.modules.pricing.domain.service import MAX_ITEMS, PriceType, Service
from app.modules.pricing.errors import PriceListFullError
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CategoryId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class AddServiceCommand:
    actor_id: UserId
    title: str
    price_type: PriceType
    description: str | None = None
    category_id: CategoryId | None = None
    price_min: int | None = None
    price_max: int | None = None
    unit: str | None = None
    duration_min: int | None = None


class AddService:
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

    async def __call__(self, cmd: AddServiceCommand) -> Service:
        # санкция на публикацию и галочка S02c — как у создания профиля (SEC-01)
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        profile_id = await profile_id_of(self._specialists, cmd.actor_id)
        async with self._uow:
            existing = await self._services.list_for_update(profile_id)
            if len(existing) >= MAX_ITEMS:
                raise PriceListFullError(limit=MAX_ITEMS)
            service = Service.add(
                profile_id=profile_id,
                title=cmd.title,
                price_type=cmd.price_type,
                now=self._clock.now(),
                position=len(existing),
                description=cmd.description,
                category_id=cmd.category_id,
                price_min=cmd.price_min,
                price_max=cmd.price_max,
                unit=cmd.unit,
                duration_min=cmd.duration_min,
            )
            await self._services.add(service)
            price_list_changed(self._uow, profile_id, cmd.actor_id, self._clock)
        return service
