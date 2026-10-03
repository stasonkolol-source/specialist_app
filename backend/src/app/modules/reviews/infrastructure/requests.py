"""Просьбы оставить отзыв (`reviews.review_requests`, 7.2): какие ещё ждут напоминания."""

from datetime import datetime

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reviews.application.ports import OpenRequest
from app.modules.reviews.domain.request import REMINDER_AFTER, RequestStage
from app.modules.reviews.domain.review import REVIEW_WINDOW
from app.modules.reviews.infrastructure.models import ReviewRequestRow, ReviewRow
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import DealId, UserId

_Q = ReviewRequestRow.__table__.c
_R = ReviewRow.__table__.c


class SqlReviewRequests:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def open(
        self, *, deal_id: DealId, client_id: UserId, performer_id: UserId, completed_at: datetime
    ) -> bool:
        self._uow.require_active()
        stmt = (
            insert(ReviewRequestRow)
            .values(
                deal_id=deal_id,
                client_id=client_id,
                performer_id=performer_id,
                completed_at=completed_at,
            )
            .on_conflict_do_nothing(index_elements=["deal_id"])
            .returning(ReviewRequestRow.deal_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def awaiting(self, now: datetime, *, limit: int) -> list[OpenRequest]:
        self._uow.require_active()
        reviewed = exists().where(
            _R.deal_id == _Q.deal_id, _R.author_id == _Q.client_id, _R.deleted_at.is_(None)
        )
        stmt = (
            select(ReviewRequestRow)
            .where(
                _Q.last_call_at.is_(None),
                _Q.completed_at <= now - REMINDER_AFTER,
                _Q.completed_at > now - REVIEW_WINDOW,
                ~reviewed,
            )
            .order_by(_Q.completed_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.scalars(stmt)).all()
        return [
            OpenRequest(
                deal_id=DealId(row.deal_id),
                client_id=UserId(row.client_id),
                performer_id=UserId(row.performer_id),
                completed_at=row.completed_at,
                reminded_at=row.reminded_at,
                last_call_at=row.last_call_at,
            )
            for row in rows
        ]

    async def mark(self, deal_id: DealId, stage: RequestStage, at: datetime) -> None:
        self._uow.require_active()
        values = {"last_call_at": at} if stage is RequestStage.LAST_CALL else {"reminded_at": at}
        await self._session.execute(
            update(ReviewRequestRow).where(_Q.deal_id == deal_id).values(**values)
        )

    async def forget(self, user_id: UserId) -> None:
        self._uow.require_active()
        await self._session.execute(
            delete(ReviewRequestRow).where(or_(_Q.client_id == user_id, _Q.performer_id == user_id))
        )
