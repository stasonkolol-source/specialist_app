"""Поправить подписку (PATCH /me/job-alerts/{id}, S18 и S19; DEVELOPMENT_PLAN 5.7): условия
целиком (форма S19), «сразу / подборкой», переключатель S18. Включить — значит и снять паузу:
человек хочет заявки сейчас. Чужая или удалённая — 404 `job_alert_not_found`."""

from dataclasses import dataclass, replace

from app.modules.catalog.api import CatalogApi
from app.modules.geo.api import GeoApi
from app.modules.jobs.application.alert_refs import check_refs
from app.modules.jobs.application.ports import JobAlerts
from app.modules.jobs.domain.alert import AlertCriteria, AlertDelivery, AlertId, JobAlert
from app.modules.jobs.errors import AlertNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateAlertCommand:
    actor_id: UserId
    alert_id: AlertId
    criteria: AlertCriteria | None = None
    delivery: AlertDelivery | None = None
    is_active: bool | None = None


class UpdateAlert:
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

    async def __call__(self, cmd: UpdateAlertCommand) -> JobAlert:
        if cmd.criteria is not None:
            await check_refs(self._catalog, self._geo, cmd.criteria)
        async with self._uow:
            await self._alerts.lock(cmd.actor_id)
            alert = await self._alerts.get(cmd.alert_id)
            if alert is None or alert.user_id != cmd.actor_id:
                raise AlertNotFoundError(alert_id=cmd.alert_id)
            edited = replace(
                alert,
                criteria=cmd.criteria or alert.criteria,
                delivery=cmd.delivery or alert.delivery,
                is_active=alert.is_active if cmd.is_active is None else cmd.is_active,
                paused_until=None if cmd.is_active else alert.paused_until,
                updated_at=self._clock.now(),
            )
            await self._alerts.save(edited)
        return edited
