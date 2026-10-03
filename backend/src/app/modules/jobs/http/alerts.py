"""HTTP подписок на новые заявки `/me/job-alerts` (S18, S19; DEVELOPMENT_PLAN 5.7; §8.5).

- `GET` — свои подписки по порядку создания и «N заявок за неделю» у каждой.
- `POST` (Idempotency-Key) — новая: до десяти, одиннадцатая — 409 `job_alerts_full`;
  категории, город и районы — из справочников (422 `invalid_job_alert`).
- `PATCH /{id}` — условия целиком, режим, переключатель S18 (включить — снять паузу).
- `DELETE /{id}` — удалить вместе с ждущими подборками.
Чужая или удалённая подписка — 404 `job_alert_not_found`. Ответы правок — та же строка S18, что
в списке: клиент кладёт её в кэш без второго запроса.
"""

from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Path, status

from app.modules.jobs.application.use_cases.create_alert import CreateAlert, CreateAlertCommand
from app.modules.jobs.application.use_cases.delete_alert import DeleteAlert, DeleteAlertCommand
from app.modules.jobs.application.use_cases.list_alerts import ListAlerts, ListAlertsCommand
from app.modules.jobs.application.use_cases.update_alert import UpdateAlert, UpdateAlertCommand
from app.modules.jobs.domain.alert import AlertId
from app.modules.jobs.errors import AlertNotFoundError
from app.modules.jobs.http.schemas import JobAlertIn, JobAlertOut, JobAlertPatchIn, JobAlertsOut
from app.platform.http.idempotency import idempotent_router
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import UserId
from app.platform.kernel.principal import Principal

alerts = APIRouter(tags=["jobs"], dependencies=AUTHENTICATED)
creating = idempotent_router()
AlertPath = Annotated[UUID, Path(description="id подписки")]


@alerts.get("/me/job-alerts", response_model=JobAlertsOut)
@inject
async def list_job_alerts(
    principal: FromDishka[Principal], listing: FromDishka[ListAlerts]
) -> JobAlertsOut:
    """Мои подписки на заявки (S18): по порядку создания, «N заявок за неделю»."""
    return JobAlertsOut.of(await listing(ListAlertsCommand(actor_id=principal.user_id)))


@creating.post(
    "/me/job-alerts",
    status_code=status.HTTP_201_CREATED,
    response_model=JobAlertOut,
    dependencies=AUTHENTICATED,
)
@inject
async def create_job_alert(
    body: JobAlertIn,
    principal: FromDishka[Principal],
    create: FromDishka[CreateAlert],
    listing: FromDishka[ListAlerts],
) -> JobAlertOut:
    """Новая подписка (S19, «Сохранить как подписку» на S14): до десяти — иначе 409
    `job_alerts_full`."""
    alert = await create(
        CreateAlertCommand(
            actor_id=principal.user_id, criteria=body.criteria.criteria(), delivery=body.delivery
        )
    )
    return await _item(listing, principal.user_id, alert.id)


@alerts.patch("/me/job-alerts/{alert_id}", response_model=JobAlertOut)
@inject
async def update_job_alert(
    alert_id: AlertPath,
    body: JobAlertPatchIn,
    principal: FromDishka[Principal],
    update: FromDishka[UpdateAlert],
    listing: FromDishka[ListAlerts],
) -> JobAlertOut:
    """Правка подписки: условия целиком (S19), режим, переключатель S18."""
    await update(
        UpdateAlertCommand(
            actor_id=principal.user_id,
            alert_id=AlertId(alert_id),
            criteria=body.criteria.criteria() if body.criteria is not None else None,
            delivery=body.delivery,
            is_active=body.is_active,
        )
    )
    return await _item(listing, principal.user_id, AlertId(alert_id))


@alerts.delete("/me/job-alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_job_alert(
    alert_id: AlertPath, principal: FromDishka[Principal], delete: FromDishka[DeleteAlert]
) -> None:
    """Удалить подписку (S18) вместе с ждущими подборками."""
    await delete(DeleteAlertCommand(actor_id=principal.user_id, alert_id=AlertId(alert_id)))


alerts.include_router(creating)


async def _item(listing: ListAlerts, user_id: UserId, alert_id: AlertId) -> JobAlertOut:
    """Строка S18 подписки — со счётчиком за неделю, как в списке."""
    items = await listing(ListAlertsCommand(actor_id=user_id))
    item = next((item for item in items if item.alert.id == alert_id), None)
    if item is None:  # удалили между правкой и чтением
        raise AlertNotFoundError(alert_id=alert_id)
    return JobAlertOut.of(item)
