"""Изменить позицию прайса (PATCH /me/profile/services/{id}, S36): переданные поля, `clear` —
обнулить; скрыть из профиля — `is_active: false` («Скрыта» в S35)."""

from collections.abc import Collection
from dataclasses import dataclass, field

from app.modules.pricing.application.ports import ServiceRepository
from app.modules.pricing.application.profile import price_list_changed, profile_id_of
from app.modules.pricing.domain.service import PriceType, Service, ServiceId
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CategoryId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ChangeServiceCommand:
    actor_id: UserId
    service_id: ServiceId
    title: str | None = None
    price_type: PriceType | None = None
    description: str | None = None
    category_id: CategoryId | None = None
    price_min: int | None = None
    price_max: int | None = None
    unit: str | None = None
    duration_min: int | None = None
    is_active: bool | None = None
    clear: Collection[str] = field(default_factory=frozenset)


class ChangeService:
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

    async def __call__(self, cmd: ChangeServiceCommand) -> Service:
        profile_id = await profile_id_of(self._specialists, cmd.actor_id)
        async with self._uow:
            service = await self._services.get_for_update(profile_id, cmd.service_id)
            service.change(
                title=cmd.title,
                price_type=cmd.price_type,
                description=cmd.description,
                category_id=cmd.category_id,
                price_min=cmd.price_min,
                price_max=cmd.price_max,
                unit=cmd.unit,
                duration_min=cmd.duration_min,
                is_active=cmd.is_active,
                clear=frozenset(cmd.clear),
            )
            await self._services.save(service)
            price_list_changed(self._uow, profile_id, cmd.actor_id, self._clock)
        return service
