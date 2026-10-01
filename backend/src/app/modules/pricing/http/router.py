"""HTTP прайса исполнителя `/me/profile/services*` (ARCHITECTURE §8.5, DEVELOPMENT_PLAN 2.8b).

Прайс — в профиле исполнителя текущего пользователя: без профиля — 409 `no_specialist_profile`.
"""

from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Path, status

from app.modules.pricing.application.queries import PriceListQueries
from app.modules.pricing.application.use_cases.add_service import AddService, AddServiceCommand
from app.modules.pricing.application.use_cases.change_service import (
    ChangeService,
    ChangeServiceCommand,
)
from app.modules.pricing.application.use_cases.remove_service import (
    RemoveService,
    RemoveServiceCommand,
)
from app.modules.pricing.application.use_cases.reorder_services import (
    ReorderServices,
    ReorderServicesCommand,
)
from app.modules.pricing.domain.service import ServiceId
from app.modules.pricing.http.schemas import (
    ServiceIn,
    ServiceOut,
    ServicesOrderIn,
    ServicesOut,
    ServiceUpdateIn,
)
from app.platform.http.idempotency import idempotent_router
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import CategoryId
from app.platform.kernel.principal import Principal

router = APIRouter(tags=["pricing"], dependencies=AUTHENTICATED)
creating = idempotent_router()
ServicePath = Annotated[UUID, Path()]


@router.get("/me/profile/services")
@inject
async def list_my_services(
    principal: FromDishka[Principal], queries: FromDishka[PriceListQueries]
) -> ServicesOut:
    """Прайс своего профиля по порядку (S35), скрытые позиции — тоже."""
    return ServicesOut(items=[ServiceOut.of(s) for s in await queries.own(principal.user_id)])


@creating.post("/me/profile/services", status_code=status.HTTP_201_CREATED)
@inject
async def add_my_service(
    body: ServiceIn, principal: FromDishka[Principal], add: FromDishka[AddService]
) -> ServiceOut:
    """Новая позиция в конец прайса (S32c, S36)."""
    service = await add(
        AddServiceCommand(
            actor_id=principal.user_id,
            title=body.title,
            price_type=body.price_type,
            description=body.description,
            category_id=CategoryId(body.category_id) if body.category_id is not None else None,
            price_min=body.price_min,
            price_max=body.price_max,
            unit=body.unit,
            duration_min=body.duration_min,
        )
    )
    return ServiceOut.of(service)


router.include_router(creating)


@router.put("/me/profile/services/order")
@inject
async def reorder_my_services(
    body: ServicesOrderIn, principal: FromDishka[Principal], reorder: FromDishka[ReorderServices]
) -> ServicesOut:
    """Порядок прайса целиком: id всех позиций в новом порядке."""
    services = await reorder(
        ReorderServicesCommand(
            actor_id=principal.user_id, service_ids=[ServiceId(i) for i in body.service_ids]
        )
    )
    return ServicesOut(items=[ServiceOut.of(s) for s in services])


@router.patch("/me/profile/services/{service_id}")
@inject
async def change_my_service(
    service_id: ServicePath,
    body: ServiceUpdateIn,
    principal: FromDishka[Principal],
    change: FromDishka[ChangeService],
) -> ServiceOut:
    """Изменить позицию (S36); `clear` — обнулить поля, `is_active: false` — скрыть."""
    service = await change(
        ChangeServiceCommand(
            actor_id=principal.user_id,
            service_id=ServiceId(service_id),
            title=body.title,
            price_type=body.price_type,
            description=body.description,
            category_id=CategoryId(body.category_id) if body.category_id is not None else None,
            price_min=body.price_min,
            price_max=body.price_max,
            unit=body.unit,
            duration_min=body.duration_min,
            is_active=body.is_active,
            clear=frozenset(body.clear),
        )
    )
    return ServiceOut.of(service)


@router.delete("/me/profile/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def remove_my_service(
    service_id: ServicePath, principal: FromDishka[Principal], remove: FromDishka[RemoveService]
) -> None:
    """Удалить позицию; порядок остальных сжимается."""
    await remove(RemoveServiceCommand(actor_id=principal.user_id, service_id=ServiceId(service_id)))
