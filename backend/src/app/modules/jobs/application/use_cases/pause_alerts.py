"""Пауза подписок из бота (DEVELOPMENT_PLAN 5.7): «Пауза подписки» под карточкой B1 — эта
подписка на неделю, `/alerts` — все включённые на сегодня или на неделю; «Снять паузу» —
`span=None`. Выключенные переключателем S18 пауза не трогает. Чужая подписка — 404."""

from dataclasses import dataclass, replace

from app.modules.jobs.application.ports import JobAlerts
from app.modules.jobs.domain.alert import AlertId, JobAlert, PauseSpan, pause_end
from app.modules.jobs.errors import AlertNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class PauseAlertsCommand:
    actor_id: UserId
    span: PauseSpan | None
    """None — снять паузу."""
    alert_id: AlertId | None = None
    """Одна подписка (кнопка B1); None — все включённые (`/alerts`)."""


class PauseAlerts:
    def __init__(self, uow: UnitOfWork, alerts: JobAlerts, clock: Clock) -> None:
        self._uow, self._alerts, self._clock = uow, alerts, clock

    async def __call__(self, cmd: PauseAlertsCommand) -> list[JobAlert]:
        """Подписки, которые поставили на паузу или с которых её сняли."""
        now = self._clock.now()
        until = pause_end(now, cmd.span) if cmd.span is not None else None
        async with self._uow:
            await self._alerts.lock(cmd.actor_id)
            mine = await self._alerts.of_user(cmd.actor_id)
            if cmd.alert_id is not None:
                mine = [alert for alert in mine if alert.id == cmd.alert_id]
                if not mine:
                    raise AlertNotFoundError(alert_id=cmd.alert_id)
            changed = [
                replace(alert, paused_until=until, updated_at=now)
                for alert in mine
                if alert.is_active
            ]
            for alert in changed:
                await self._alerts.save(alert)
        return changed
