"""Чтение сделок (S25, S26, списки; ADR-0020 §5): без блокировок, вне UoW."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, RowMapping, and_, func, or_, select, tuple_

from app.modules.deals.application.dto import DealView
from app.modules.deals.application.ports import DealSweep
from app.modules.deals.domain.deal import (
    AUTO_COMPLETE_AFTER,
    PROMPT_DELAY,
    PROMPT_WITHOUT_TIME,
    PROPOSAL_TTL,
    REMINDER_LEAD,
    DealRole,
    DealStatus,
)
from app.modules.deals.infrastructure.models import DealRow
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.kernel.ids import CategoryId, DealId, UserId
from app.platform.kernel.pagination import Page, PageRequest

_D = DealRow


class SqlDealQueries(SqlQuery):
    async def view(self, deal_id: DealId) -> DealView | None:
        row = await self._fetch_one(select(DealRow.__table__).where(_D.id == deal_id))
        return _view(row) if row is not None else None

    async def mine(
        self,
        user_id: UserId,
        *,
        role: DealRole | None,
        statuses: Sequence[DealStatus],
        page: PageRequest,
    ) -> Page[DealView]:
        if role is DealRole.CLIENT:
            stmt = select(DealRow.__table__).where(_D.client_id == user_id)
        elif role is DealRole.PERFORMER:
            stmt = select(DealRow.__table__).where(_D.performer_id == user_id)
        else:
            stmt = select(DealRow.__table__).where(
                or_(_D.client_id == user_id, _D.performer_id == user_id)
            )
        if statuses:
            stmt = stmt.where(_D.status.in_([status.value for status in statuses]))
        if page.cursor is not None:
            created_at, deal_id = decode_cursor(page.cursor, (datetime, UUID))
            stmt = stmt.where(tuple_(_D.created_at, _D.id) < tuple_(created_at, deal_id))
        rows = await self._fetch(
            stmt.order_by(_D.created_at.desc(), _D.id.desc()).limit(page.limit + 1)
        )
        items = [_view(row) for row in rows[: page.limit]]
        last = items[-1] if items else None
        more = len(rows) > page.limit
        cursor = encode_cursor(last.created_at, last.id) if more and last else None
        return Page(items=tuple(items), next_cursor=cursor)

    async def due(self, sweep: DealSweep, now: datetime, *, limit: int) -> list[DealId]:
        rows = await self._fetch(
            select(_D.id).where(_due(sweep, now)).order_by(_D.created_at, _D.id).limit(limit)
        )
        return [DealId(row["id"]) for row in rows]


def _due(sweep: DealSweep, now: datetime) -> ColumnElement[bool]:
    """Условие прохода; метод сделки перепроверит его под блокировкой строки."""
    agreed = _D.status == DealStatus.AGREED.value
    if sweep is DealSweep.REMIND:
        return and_(
            agreed,
            _D.reminded_at.is_(None),
            _D.scheduled_at > now,
            _D.scheduled_at <= now + REMINDER_LEAD,
        )
    if sweep is DealSweep.PROMPT:
        return and_(
            agreed,
            _D.completion_prompted_at.is_(None),
            or_(
                _D.scheduled_at <= now - PROMPT_DELAY,
                and_(_D.scheduled_at.is_(None), _D.agreed_at <= now - PROMPT_WITHOUT_TIME),
            ),
        )
    if sweep is DealSweep.AUTO_COMPLETE:
        marked = func.coalesce(_D.client_confirmed_at, _D.performer_confirmed_at)
        return and_(
            agreed,
            _D.client_confirmed_at.is_(None) != _D.performer_confirmed_at.is_(None),
            marked <= now - AUTO_COMPLETE_AFTER,
        )
    return and_(_D.status == DealStatus.PROPOSED.value, _D.created_at <= now - PROPOSAL_TTL)


def _view(row: RowMapping) -> DealView:
    return DealView(
        id=DealId(row["id"]),
        client_id=UserId(row["client_id"]),
        performer_id=UserId(row["performer_id"]),
        profile_id=row["profile_id"],
        origin=row["origin"],
        status=row["status"],
        title=row["title_snapshot"],
        category_id=CategoryId(row["category_id"]) if row["category_id"] is not None else None,
        price_type=row["price_type"],
        agreed_price=row["agreed_price"],
        scheduled_at=row["scheduled_at"],
        job_id=row["job_id"],
        response_id=row["response_id"],
        conversation_id=row["conversation_id"],
        proposed_by=UserId(row["proposed_by"]) if row["proposed_by"] is not None else None,
        agreed_at=row["agreed_at"],
        client_confirmed_at=row["client_confirmed_at"],
        performer_confirmed_at=row["performer_confirmed_at"],
        completed_at=row["completed_at"],
        cancelled_at=row["cancelled_at"],
        cancelled_by=UserId(row["cancelled_by"]) if row["cancelled_by"] is not None else None,
        cancel_reason=row["cancel_reason"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
