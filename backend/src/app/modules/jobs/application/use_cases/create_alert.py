"""Новая подписка на заявки (POST /me/job-alerts, S19 и «Сохранить как подписку» на S14;
DEVELOPMENT_PLAN 5.7): не больше десяти — одиннадцатая 409 `job_alerts_full`. Категории, город и
районы — из справочников (иначе 422 `invalid_job_alert`). Параллельные «Сохранить» сериализует
блокировка пользователя. В аналитику — `alert_created`."""

from dataclasses import dataclass

from app.modules.catalog.api import CatalogApi
from app.modules.geo.api import GeoApi
from app.modules.jobs.application.alert_refs import check_refs
from app.modules.jobs.application.ports import JobAlerts
from app.modules.jobs.domain.alert import (
    MAX_ALERTS,
    AlertCriteria,
    AlertDelivery,
    AlertId,
    JobAlert,
)
from app.modules.jobs.domain.job import Urgency
from app.modules.jobs.errors import AlertsFullError
from app.platform.contracts.events.jobs import AlertCreated
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId, new_id


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateAlertCommand:
    actor_id: UserId
    criteria: AlertCriteria
    delivery: AlertDelivery = AlertDelivery.INSTANT


class CreateAlert:
    def __init__(
        self,
        uow: UnitOfWork,
        alerts: JobAlerts,
        catalog: CatalogApi,
        geo: GeoApi,
        clock: Clock,
    ) -> None:
        self._uow, self._alerts, self._catalog, self._geo = uow, alerts, catalog, geo
        self._clock = clock

    async def __call__(self, cmd: CreateAlertCommand) -> JobAlert:
        await check_refs(self._catalog, self._geo, cmd.criteria)
        now = self._clock.now()
        async with self._uow:
            await self._alerts.lock(cmd.actor_id)
            if len(await self._alerts.of_user(cmd.actor_id)) >= MAX_ALERTS:
                raise AlertsFullError(limit=MAX_ALERTS)
            alert = JobAlert(
                id=AlertId(new_id()),
                user_id=cmd.actor_id,
                criteria=cmd.criteria,
                delivery=cmd.delivery,
                is_active=True,
                paused_until=None,
                created_at=now,
                updated_at=now,
            )
            await self._alerts.add(alert)
            self._uow.add_event(_created(alert))
        return alert


def _created(alert: JobAlert) -> AlertCreated:
    criteria = alert.criteria
    area = "radius" if criteria.center else "districts" if criteria.district_ids else "city"
    return AlertCreated(
        alert_id=alert.id,
        user_id=alert.user_id,
        city_id=criteria.city_id,
        delivery=alert.delivery.value,
        area=area,
        categories=len(criteria.category_ids),
        has_budget=criteria.min_budget is not None,
        urgent_only=criteria.urgencies == (Urgency.ASAP,),
        occurred_at=alert.created_at,
    )
