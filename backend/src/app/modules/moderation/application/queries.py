"""Запросы модерации для дашбордов (ADR-0020 §4: до use case — только чтение)."""

from datetime import datetime

from app.modules.moderation.application.dto import QueueSla
from app.modules.moderation.application.ports import CaseStats
from app.platform.kernel.clock import Clock


class ModerationQueries:
    def __init__(self, stats: CaseStats, clock: Clock) -> None:
        self._stats, self._clock = stats, clock

    async def sla(self, *, since: datetime, until: datetime | None = None) -> list[QueueSla]:
        """SLA по очередям за период (дашборд 6.6): доля решённых в срок, просроченные."""
        now = self._clock.now()
        return await self._stats.sla(since=since, until=until or now, now=now)
