"""Репозиторий отзывов (ADR-0020 §5). Второй отзыв автора по сделке упирается в частичный
уникальный индекс `uq_reviews_deal_id_author_id` — ReviewExistsError."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reviews.domain.review import (
    Criterion,
    Reply,
    ReplyStatus,
    Review,
    ReviewId,
)
from app.modules.reviews.errors import ReviewExistsError, ReviewNotFoundError
from app.modules.reviews.infrastructure.models import ReviewRow
from app.platform.db.constraints import raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.db.versioning import check_loaded_version
from app.platform.kernel.ids import CategoryId, DealId, UserId

UNIQUE_REVIEW = "uq_reviews_deal_id_author_id"


class SqlReviewRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def add(self, review: Review) -> None:
        self._uow.require_active()
        row = ReviewRow(id=review.id, version=review.version, created_at=review.created_at)
        _apply(review, row)
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise_domain_error(
                err, {UNIQUE_REVIEW: lambda: ReviewExistsError(deal_id=review.deal_id)}
            )
        self._uow.track(review)

    async def get_for_update(self, review_id: ReviewId) -> Review:
        review = await self.find_for_update(review_id)
        if review is None:
            raise ReviewNotFoundError(review_id=review_id)
        return review

    async def find_for_update(self, review_id: ReviewId) -> Review | None:
        self._uow.require_active()
        stmt = (
            select(ReviewRow)
            .where(ReviewRow.id == review_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        review = _to_domain(row)
        self._uow.track(review)
        return review

    async def save(self, review: Review) -> None:
        self._uow.require_active()
        row = await self._session.get(ReviewRow, review.id)
        if row is None:
            raise ReviewNotFoundError(review_id=review.id)
        check_loaded_version(entity="review", loaded=row.version, expected=review.version)
        _apply(review, row)
        row.version = review.version + 1
        await self._session.flush()
        review.mark_persisted(version=row.version)
        self._uow.track(review)

    async def written_by(self, user_id: UserId) -> list[ReviewId]:
        stmt = select(ReviewRow.id).where(
            ReviewRow.author_id == user_id, ReviewRow.deleted_at.is_(None)
        )
        return [ReviewId(value) for value in (await self._session.scalars(stmt)).all()]

    async def replied_by(self, user_id: UserId) -> list[ReviewId]:
        stmt = select(ReviewRow.id).where(
            ReviewRow.subject_user_id == user_id, ReviewRow.reply_body.is_not(None)
        )
        return [ReviewId(value) for value in (await self._session.scalars(stmt)).all()]

    async def of_deal(self, deal_id: DealId, author_id: UserId) -> ReviewId | None:
        stmt = select(ReviewRow.id).where(
            ReviewRow.deal_id == deal_id,
            ReviewRow.author_id == author_id,
            ReviewRow.deleted_at.is_(None),
        )
        found = (await self._session.execute(stmt)).scalar_one_or_none()
        return ReviewId(found) if found is not None else None


def _to_domain(row: ReviewRow) -> Review:
    reply = None
    if row.reply_body is not None and row.reply_at is not None and row.reply_status is not None:
        reply = Reply(body=row.reply_body, at=row.reply_at, status=ReplyStatus(row.reply_status))
    return Review(
        id=ReviewId(row.id),
        kind=row.kind,
        deal_id=DealId(row.deal_id) if row.deal_id is not None else None,
        author_id=UserId(row.author_id),
        subject_user_id=UserId(row.subject_user_id),
        subject_profile_id=row.subject_profile_id,
        category_id=CategoryId(row.category_id) if row.category_id is not None else None,
        direction=row.direction,
        rating=row.rating,
        criteria={Criterion(name): int(value) for name, value in row.criteria.items()},
        body=row.body,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        published_at=row.published_at,
        reply=reply,
        deleted_at=row.deleted_at,
        version=row.version,
    )


def _apply(review: Review, row: ReviewRow) -> None:
    row.kind = review.kind
    row.deal_id = review.deal_id
    row.author_id = review.author_id
    row.subject_user_id = review.subject_user_id
    row.subject_profile_id = review.subject_profile_id
    row.category_id = review.category_id
    row.direction = review.direction
    row.rating = review.rating
    row.criteria = {criterion.value: value for criterion, value in review.criteria.items()}
    row.body = review.body
    row.status = review.status
    row.reply_body = review.reply.body if review.reply is not None else None
    row.reply_at = review.reply.at if review.reply is not None else None
    row.reply_status = review.reply.status if review.reply is not None else None
    row.published_at = review.published_at
    row.updated_at = review.updated_at
    row.deleted_at = review.deleted_at
