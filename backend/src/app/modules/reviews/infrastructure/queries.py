"""Чтение отзывов для экранов (CQRS-lite, ADR-0020 §4): карточка специалиста (S08, S11), свои
отзывы по сделкам (S26, S27), «Мои отзывы» (S28). Keyset по (дата, id), новые первыми."""

from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping, Select, func, select, tuple_

from app.modules.reviews.api import MyReview, PublicReview, ReplyView
from app.modules.reviews.application.dto import ReviewsDirection, UserReview
from app.modules.reviews.domain.review import ReplyStatus, ReviewKind, ReviewStatus
from app.modules.reviews.infrastructure.models import ReviewRow
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.kernel.ids import DealId, UserId
from app.platform.kernel.pagination import Page, PageRequest

_T = ReviewRow.__table__
_R = _T.c


class SqlReviewQueries(SqlQuery):
    async def public_of(
        self, profile_id: UUID, page: PageRequest, kind: ReviewKind
    ) -> Page[PublicReview]:
        stmt: Select[Any] = select(_T).where(
            _R.subject_profile_id == profile_id,
            _R.kind == kind.value,
            _R.status == ReviewStatus.PUBLISHED.value,
            _R.deleted_at.is_(None),
        )
        if page.cursor is not None:
            at, review_id = decode_cursor(page.cursor, (datetime, UUID))
            stmt = stmt.where(tuple_(_R.published_at, _R.id) < tuple_(at, review_id))
        rows = await self._fetch(
            stmt.order_by(_R.published_at.desc(), _R.id.desc()).limit(page.limit + 1)
        )
        items = [_public(row) for row in rows[: page.limit]]
        cursor = None
        if len(rows) > page.limit and items:
            cursor = encode_cursor(items[-1].published_at, items[-1].id)
        return Page(items=tuple(items), next_cursor=cursor)

    async def count_of(self, profile_id: UUID, kind: ReviewKind) -> int:
        row = await self._fetch_one(
            select(func.count().label("count")).where(
                _R.subject_profile_id == profile_id,
                _R.kind == kind.value,
                _R.status == ReviewStatus.PUBLISHED.value,
                _R.deleted_at.is_(None),
            )
        )
        return int(row["count"]) if row is not None else 0

    async def public(self, review_id: UUID) -> PublicReview | None:
        row = await self._fetch_one(
            select(_T).where(
                _R.id == review_id,
                _R.status == ReviewStatus.PUBLISHED.value,
                _R.deleted_at.is_(None),
            )
        )
        return _public(row) if row is not None else None

    async def mine(self, author_id: UserId, deal_ids: Collection[DealId]) -> dict[DealId, MyReview]:
        if not deal_ids:
            return {}
        rows = await self._fetch(
            select(_R.id, _R.deal_id, _R.status, _R.rating).where(
                _R.author_id == author_id,
                _R.deal_id.in_(list(deal_ids)),
                _R.deleted_at.is_(None),
            )
        )
        return {
            DealId(row["deal_id"]): MyReview(
                id=row["id"], status=row["status"], rating=row["rating"]
            )
            for row in rows
        }

    async def of_user(
        self, user_id: UserId, direction: ReviewsDirection, page: PageRequest
    ) -> Page[UserReview]:
        stmt: Select[Any] = select(_T).where(_R.deleted_at.is_(None))
        if direction is ReviewsDirection.RECEIVED:
            stmt = stmt.where(
                _R.subject_user_id == user_id, _R.status == ReviewStatus.PUBLISHED.value
            )
        else:
            stmt = stmt.where(_R.author_id == user_id)
        if page.cursor is not None:
            at, review_id = decode_cursor(page.cursor, (datetime, UUID))
            stmt = stmt.where(tuple_(_R.created_at, _R.id) < tuple_(at, review_id))
        rows = await self._fetch(
            stmt.order_by(_R.created_at.desc(), _R.id.desc()).limit(page.limit + 1)
        )
        items = [_user_review(row, direction) for row in rows[: page.limit]]
        cursor = None
        if len(rows) > page.limit and items:
            cursor = encode_cursor(items[-1].created_at, items[-1].id)
        return Page(items=tuple(items), next_cursor=cursor)


def _public(row: RowMapping) -> PublicReview:
    reply = None
    if row["reply_status"] == ReplyStatus.PUBLISHED.value:
        reply = ReplyView(body=row["reply_body"], at=row["reply_at"])
    return PublicReview(
        id=row["id"],
        kind=row["kind"],
        author_id=UserId(row["author_id"]),
        subject_profile_id=row["subject_profile_id"],
        rating=row["rating"],
        criteria={name: int(value) for name, value in row["criteria"].items()},
        body=row["body"],
        category_id=row["category_id"],
        published_at=row["published_at"],
        reply=reply,
        work_title=row["work_title"],
    )


def _user_review(row: RowMapping, direction: ReviewsDirection) -> UserReview:
    received = direction is ReviewsDirection.RECEIVED
    return UserReview(
        id=row["id"],
        kind=row["kind"],
        work_title=row["work_title"],
        deal_id=DealId(row["deal_id"]) if row["deal_id"] is not None else None,
        counterpart_id=UserId(row["author_id"] if received else row["subject_user_id"]),
        rating=row["rating"],
        criteria={name: int(value) for name, value in row["criteria"].items()},
        body=row["body"],
        status=row["status"],
        reply_body=row["reply_body"],
        reply_status=row["reply_status"],
        reply_at=row["reply_at"],
        created_at=row["created_at"],
        published_at=row["published_at"],
    )
