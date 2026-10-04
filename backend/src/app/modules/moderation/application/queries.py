"""Запросы модерации для дашбордов и Admin API (ADR-0020 §4: до use case — только чтение)."""

from datetime import datetime
from uuid import UUID

from app.modules.moderation.application.dto import (
    CaseFilter,
    OpenCaseView,
    QueueSla,
    ReportFilter,
    StaffCaseView,
    StaffReportView,
)
from app.modules.moderation.application.ports import CaseQueue, CaseStats, StaffCaseQuery
from app.modules.moderation.errors import CaseNotFoundError, ReportNotFoundError
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CaseId
from app.platform.kernel.pagination import Page, PageRequest


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


class StaffQueries:
    """Очередь кейсов и жалобы для Admin API (2.7b); решения — use cases (ADR-0020 §1)."""

    def __init__(self, staff: StaffCaseQuery) -> None:
        self._staff = staff

    async def cases(self, query: CaseFilter, page: PageRequest) -> Page[StaffCaseView]:
        return await self._staff.cases(query, page)

    async def case(self, case_id: CaseId) -> StaffCaseView:
        found = await self._staff.case(case_id)
        if found is None:
            raise CaseNotFoundError(case_id=case_id)
        return found

    async def reports(self, query: ReportFilter, page: PageRequest) -> Page[StaffReportView]:
        return await self._staff.reports(query, page)

    async def report(self, report_id: UUID) -> StaffReportView:
        found = await self._staff.report(report_id)
        if found is None:
            raise ReportNotFoundError(report_id=report_id)
        return found
