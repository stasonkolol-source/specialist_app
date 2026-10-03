"""Чтение сделок и споров (S25, S26, S52, списки; ADR-0020 §5): без блокировок, вне UoW; legal
hold споров — в транзакции вызывающего (очистка media, удаление аккаунта)."""

from collections.abc import Collection, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, RowMapping, and_, func, or_, select, tuple_, union

from app.modules.deals.application.dto import DealView, DisputeView
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
from app.modules.deals.domain.dispute import ACTIVE as ACTIVE_DISPUTES
from app.modules.deals.domain.dispute import DisputeId, DisputeStatus
from app.modules.deals.infrastructure.models import DealRow, DisputeRow
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.kernel.ids import CategoryId, DealId, MediaId, UserId
from app.platform.kernel.pagination import Page, PageRequest

_D = DealRow


class SqlDealQueries(SqlQuery):
    async def view(self, deal_id: DealId) -> DealView | None:
        row = await self._fetch_one(select(DealRow.__table__).where(_D.id == deal_id))
        return _view(row) if row is not None else None

    async def views(self, deal_ids: Collection[DealId]) -> list[DealView]:
        if not deal_ids:
            return []
        rows = await self._fetch(select(DealRow.__table__).where(_D.id.in_(list(deal_ids))))
        return [_view(row) for row in rows]

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

    async def of_response(self, response_id: UUID) -> DealId | None:
        row = await self._fetch_one(select(_D.id).where(_D.response_id == response_id))
        return DealId(row["id"]) if row is not None else None

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


_P = DisputeRow
_ACTIVE_DISPUTE = [status.value for status in ACTIVE_DISPUTES]


class SqlDisputeQueries(SqlQuery):
    async def view(self, dispute_id: DisputeId) -> DisputeView | None:
        row = await self._fetch_one(select(DisputeRow.__table__).where(_P.id == dispute_id))
        return _dispute_view(row) if row is not None else None

    async def latest(self, deal_id: DealId) -> DisputeView | None:
        row = await self._fetch_one(
            select(DisputeRow.__table__)
            .where(_P.deal_id == deal_id)
            .order_by(_P.created_at.desc(), _P.id.desc())
            .limit(1)
        )
        return _dispute_view(row) if row is not None else None

    async def unanswered_due(self, now: datetime, *, limit: int) -> list[DisputeId]:
        rows = await self._fetch(
            select(_P.id)
            .where(_P.status == DisputeStatus.OPEN.value, _P.respond_by <= now)
            .order_by(_P.respond_by, _P.id)
            .limit(limit)
        )
        return [DisputeId(row["id"]) for row in rows]

    async def disputing(self, user_ids: Collection[UserId]) -> frozenset[UserId]:
        wanted = list(set(user_ids))
        if not wanted:
            return frozenset()
        active = _P.status.in_(_ACTIVE_DISPUTE)
        opened = select(_P.opened_by.label("user_id")).where(active, _P.opened_by.in_(wanted))
        answering = select(_P.respondent_id.label("user_id")).where(
            active, _P.respondent_id.in_(wanted)
        )
        rows = await self._fetch(union(opened, answering))
        return frozenset(UserId(row["user_id"]) for row in rows)

    async def evidence_held(self, media_ids: Collection[MediaId]) -> frozenset[MediaId]:
        wanted = set(media_ids)
        if not wanted:
            return frozenset()
        ids = list(wanted)
        active = _P.status.in_(_ACTIVE_DISPUTE)
        rows = await self._fetch(
            select(_P.media_ids, _P.response_media_ids).where(
                active, or_(_P.media_ids.overlap(ids), _P.response_media_ids.overlap(ids))
            )
        )
        held = {
            MediaId(media_id)
            for row in rows
            for media_id in (*row["media_ids"], *row["response_media_ids"])
            if media_id in wanted
        }
        return frozenset(held)


def _dispute_view(row: RowMapping) -> DisputeView:
    return DisputeView(
        id=DisputeId(row["id"]),
        deal_id=DealId(row["deal_id"]),
        opened_by=UserId(row["opened_by"]),
        respondent_id=UserId(row["respondent_id"]),
        kind=row["kind"],
        description=row["description"],
        media_ids=tuple(MediaId(media_id) for media_id in row["media_ids"]),
        respond_by=row["respond_by"],
        status=row["status"],
        response=row["response"],
        response_media_ids=tuple(MediaId(media_id) for media_id in row["response_media_ids"]),
        responded_at=row["responded_at"],
        unanswered_at=row["unanswered_at"],
        withdrawn_at=row["withdrawn_at"],
        outcome=row["outcome"],
        reason_code=row["reason_code"],
        resolved_by=UserId(row["resolved_by"]) if row["resolved_by"] is not None else None,
        resolved_at=row["resolved_at"],
        created_at=row["created_at"],
    )
