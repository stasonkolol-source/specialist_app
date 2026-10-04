"""Мои подписки на заявки (GET /me/job-alerts, S18; DEVELOPMENT_PLAN 5.7): по порядку создания и
«N заявок за неделю» у каждой — сколько опубликованных за 7 дней заявок ей подходит (без своих и
заявок тех, с кем у исполнителя блокировка)."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from app.modules.identity.api import IdentityApi
from app.modules.jobs.application.alerts import AlertItem
from app.modules.jobs.application.ports import JobAlerts, JobQueries
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId

STATS_WINDOW: Final = timedelta(days=7)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListAlertsCommand:
    actor_id: UserId


class ListAlerts:
    def __init__(
        self, alerts: JobAlerts, queries: JobQueries, identity: IdentityApi, clock: Clock
    ) -> None:
        self._alerts, self._queries, self._identity, self._clock = alerts, queries, identity, clock

    async def __call__(self, query: ListAlertsCommand) -> list[AlertItem]:
        alerts = await self._alerts.of_user(query.actor_id)
        if not alerts:
            return []
        hidden = await self._identity.blocked_ids(query.actor_id)
        counts = await self._queries.alert_counts(
            query.actor_id, since=self._clock.now() - STATS_WINDOW, hidden_clients=hidden
        )
        return [AlertItem(alert=alert, week_count=counts.get(alert.id, 0)) for alert in alerts]
