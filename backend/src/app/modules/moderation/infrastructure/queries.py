"""Запросы модерации (ADR-0020 §4): SLA очередей для дашборда 6.6."""

from datetime import datetime

from sqlalchemy import and_, func, or_, select

from app.modules.moderation.application.dto import QueueSla
from app.modules.moderation.domain.cases import OPEN
from app.modules.moderation.domain.queues import PRIORITY
from app.modules.moderation.infrastructure.models import CaseRow
from app.platform.db.query import SqlQuery


class SqlCaseStats(SqlQuery):
    async def sla(self, *, since: datetime, until: datetime, now: datetime) -> list[QueueSla]:
        c = CaseRow.__table__.c
        decided = and_(c.decided_at >= since, c.decided_at < until)
        is_open = c.status.in_([status.value for status in OPEN])
        rows = await self._fetch(
            select(
                c.queue,
                func.count().filter(decided).label("decided"),
                func.count().filter(decided, c.decided_at <= c.due_at).label("in_time"),
                func.count().filter(is_open).label("open"),
                func.count().filter(is_open, c.due_at < now).label("overdue"),
            )
            .where(or_(decided, is_open))
            .group_by(c.queue)
        )
        by_queue = {row["queue"]: row for row in rows}
        return [
            QueueSla(
                queue=queue,
                decided=int(row["decided"]) if (row := by_queue.get(queue)) else 0,
                decided_in_time=int(row["in_time"]) if row else 0,
                open=int(row["open"]) if row else 0,
                overdue=int(row["overdue"]) if row else 0,
            )
            for queue in PRIORITY
        ]
