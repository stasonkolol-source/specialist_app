"""Запросы модерации (ADR-0020 §4): SLA очередей для дашборда 6.6, открытые кейсы для
`cli moderation-queue`, кейсы и жалобы для Admin API (2.7b)."""

from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import RowMapping, Select, and_, func, or_, select, tuple_

from app.modules.moderation.application.dto import (
    CaseFilter,
    OpenCaseView,
    QueueSla,
    ReportFilter,
    StaffCaseView,
    StaffReportView,
)
from app.modules.moderation.domain.cases import OPEN
from app.modules.moderation.domain.queues import PRIORITY
from app.modules.moderation.infrastructure.models import CaseRow, ReportRow
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.kernel.ids import CaseId, MediaId, UserId
from app.platform.kernel.pagination import InvalidCursorError, Page, PageRequest


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


class SqlCaseQueue(SqlQuery):
    async def open_cases(self, *, limit: int) -> list[OpenCaseView]:
        c = CaseRow.__table__.c
        rows = await self._fetch(
            select(
                c.id, c.queue, c.entity_type, c.entity_id, c.trigger, c.status, c.due_at, c.evidence
            )
            .where(c.status.in_([status.value for status in OPEN]))
            .order_by(c.due_at, c.id)
            .limit(limit)
        )
        return [
            OpenCaseView(
                id=CaseId(row["id"]),
                queue=row["queue"],
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                trigger=row["trigger"],
                status=row["status"],
                due_at=row["due_at"],
                signals=tuple(
                    str(signal) for entry in row["evidence"] for signal in entry.get("signals", ())
                ),
            )
            for row in rows
        ]


_DUE: Final = "due"
_RECENT: Final = "recent"


class SqlStaffCaseQuery(SqlQuery):
    """Кейсы и жалобы для Admin API: keyset — `(due_at, id)` по сроку или `(created_at, id)` от
    новых; в курсоре и порядок — курсор одного порядка в другом не примут."""

    async def cases(self, query: CaseFilter, page: PageRequest) -> Page[StaffCaseView]:
        c = CaseRow.__table__.c
        order = _RECENT if query.recent_first else _DUE
        key = c.created_at if query.recent_first else c.due_at
        stmt = _case_filter(select(CaseRow.__table__), query).limit(page.limit + 1)
        if query.recent_first:
            stmt = stmt.order_by(key.desc(), c.id.desc())
        else:
            stmt = stmt.order_by(key, c.id)
        if page.cursor is not None:
            kind, at, last = decode_cursor(page.cursor, (str, datetime, UUID))
            if kind != order:
                raise InvalidCursorError
            after = (
                tuple_(key, c.id) < (at, last)
                if query.recent_first
                else (tuple_(key, c.id) > (at, last))
            )
            stmt = stmt.where(after)
        rows = await self._fetch(stmt)
        items = tuple(_case(row) for row in rows[: page.limit])
        if len(rows) <= page.limit:
            return Page(items=items)
        last_row = rows[page.limit - 1]
        at = last_row["created_at"] if query.recent_first else last_row["due_at"]
        return Page(items=items, next_cursor=encode_cursor(order, at, last_row["id"]))

    async def case(self, case_id: CaseId) -> StaffCaseView | None:
        row = await self._fetch_one(select(CaseRow.__table__).where(CaseRow.id == case_id))
        return _case(row) if row is not None else None

    async def reports(self, query: ReportFilter, page: PageRequest) -> Page[StaffReportView]:
        r = ReportRow.__table__.c
        stmt = (
            _report_filter(select(ReportRow.__table__), query)
            .order_by(r.created_at.desc(), r.id.desc())
            .limit(page.limit + 1)
        )
        if page.cursor is not None:
            at, last = decode_cursor(page.cursor, (datetime, UUID))
            stmt = stmt.where(tuple_(r.created_at, r.id) < (at, last))
        rows = await self._fetch(stmt)
        items = tuple(_report(row) for row in rows[: page.limit])
        if len(rows) <= page.limit:
            return Page(items=items)
        tail = items[-1]
        return Page(items=items, next_cursor=encode_cursor(tail.created_at, tail.id))

    async def report(self, report_id: UUID) -> StaffReportView | None:
        row = await self._fetch_one(select(ReportRow.__table__).where(ReportRow.id == report_id))
        return _report(row) if row is not None else None


def _case_filter(stmt: Select[Any], query: CaseFilter) -> Select[Any]:
    c = CaseRow.__table__.c
    if query.queues:
        stmt = stmt.where(c.queue.in_([queue.value for queue in query.queues]))
    if query.statuses:
        stmt = stmt.where(c.status.in_([status.value for status in query.statuses]))
    if query.entity_type is not None:
        stmt = stmt.where(c.entity_type == query.entity_type.value)
    if query.subject_id is not None:
        stmt = stmt.where(c.subject_id == query.subject_id)
    if query.assigned_to is not None:
        stmt = stmt.where(c.assigned_to == query.assigned_to)
    return stmt


def _report_filter(stmt: Select[Any], query: ReportFilter) -> Select[Any]:
    r = ReportRow.__table__.c
    if query.statuses:
        stmt = stmt.where(r.status.in_([status.value for status in query.statuses]))
    if query.target_type is not None:
        stmt = stmt.where(r.target_type == query.target_type.value)
    if query.target_id is not None:
        stmt = stmt.where(r.target_id == query.target_id)
    if query.case_id is not None:
        stmt = stmt.where(r.case_id == query.case_id)
    if query.reporter_id is not None:
        stmt = stmt.where(r.reporter_id == query.reporter_id)
    return stmt


def _case(row: RowMapping) -> StaffCaseView:
    return StaffCaseView(
        id=CaseId(row["id"]),
        queue=row["queue"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        subject_id=UserId(row["subject_id"]),
        trigger=row["trigger"],
        status=row["status"],
        opened_at=row["created_at"],
        due_at=row["due_at"],
        evidence=tuple(row["evidence"] or ()),
        media_ids=tuple(MediaId(media_id) for media_id in row["media_ids"] or ()),
        appeal_of=_case_id(row["appeal_of"]),
        assigned_to=_user_id(row["assigned_to"]),
        decided_by=_user_id(row["decided_by"]),
        reason_code=row["reason_code"],
        policy_version=row["policy_version"],
        decided_at=row["decided_at"],
        notes=row["notes"],
    )


def _report(row: RowMapping) -> StaffReportView:
    return StaffReportView(
        id=row["id"],
        reporter_id=UserId(row["reporter_id"]),
        target_type=row["target_type"],
        target_id=row["target_id"],
        reason=row["reason"],
        comment=row["comment"],
        is_legal_notice=row["is_legal_notice"],
        case_id=_case_id(row["case_id"]),
        status=row["status"],
        resolution=row["resolution"],
        resolved_by=_user_id(row["resolved_by"]),
        resolved_at=row["resolved_at"],
        created_at=row["created_at"],
    )


def _user_id(value: UUID | None) -> UserId | None:
    return UserId(value) if value is not None else None


def _case_id(value: UUID | None) -> CaseId | None:
    return CaseId(value) if value is not None else None
