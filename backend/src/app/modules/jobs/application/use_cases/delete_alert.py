"""Удалить подписку (DELETE /me/job-alerts/{id}, «Удалить» на S18; DEVELOPMENT_PLAN 5.7): вместе с
ждущими подборками. Чужая или уже удалённая — 404 `job_alert_not_found`."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobAlerts
from app.modules.jobs.domain.alert import AlertId
from app.modules.jobs.errors import AlertNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class DeleteAlertCommand:
    actor_id: UserId
    alert_id: AlertId


class DeleteAlert:
    def __init__(self, uow: UnitOfWork, alerts: JobAlerts) -> None:
        self._uow, self._alerts = uow, alerts

    async def __call__(self, cmd: DeleteAlertCommand) -> None:
        async with self._uow:
            await self._alerts.lock(cmd.actor_id)
            alert = await self._alerts.get(cmd.alert_id)
            if alert is None or alert.user_id != cmd.actor_id:
                raise AlertNotFoundError(alert_id=cmd.alert_id)
            await self._alerts.delete(alert.id)
