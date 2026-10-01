"""Запросы модерации для дашбордов (ADR-0020 §4: до use case — только чтение)."""

from datetime import datetime

from app.modules.moderation.application.dto import OpenCaseView, QueueSla
from app.modules.moderation.application.ports import CaseQueue, CaseStats
from app.platform.kernel.clock import Clock


class ModerationQueries:
    def __init__(self, stats: CaseStats, queue: CaseQueue, clock: Clock) -> None:
        self._stats, self._queue, self._clock = stats, queue, clock

    async def open_cases(self, *, limit: int = 50) -> list[OpenCaseView]:
        """Открытые кейсы по сроку (`cli moderation-queue`, до чата модераторов 2.5b)."""
        return await self._queue.open_cases(limit=limit)

    async def sla(self, *, since: datetime, until: datetime | None = None) -> list[QueueSla]:
        """SLA по очередям за период (дашборд 6.6): доля решённых в срок, просроченные."""
        now = self._clock.now()
        return await self._stats.sla(since=since, until=until or now, now=now)
