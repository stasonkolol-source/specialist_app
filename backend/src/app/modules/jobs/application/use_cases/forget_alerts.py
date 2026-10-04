"""Удаление аккаунта (UserDeleted, §7.10; DEVELOPMENT_PLAN 5.7): подписки исполнителя и совпадения
заявок с ними удаляются — в них район, точка и интересы человека."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobAlerts
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetAlertsCommand:
    user_id: UserId


class ForgetAlerts:
    def __init__(self, uow: UnitOfWork, alerts: JobAlerts) -> None:
        self._uow, self._alerts = uow, alerts

    async def __call__(self, cmd: ForgetAlertsCommand) -> None:
        async with self._uow:
            await self._alerts.forget(cmd.user_id)
