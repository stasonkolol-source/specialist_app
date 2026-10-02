"""Реализация ReviewsApi (ADR-0020 §6): рейтинг и отзывы для карточки специалиста, выдачи и
сделки; проверка отзывов и ответов для модерации (адаптеры целей `review` и `review_reply`).

Методы проверки, которые меняют отзыв, идут в транзакции вызывающего (модерация публикует или
снимает объект вместе со своим кейсом); чтение текста для проверки — в своей.
"""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from app.modules.reviews.api import (
    DealReviewState,
    PublicReview,
    RatingSummary,
    ReviewForCheck,
    ReviewsApi,
)
from app.modules.reviews.application.ports import RatingStore, ReviewQueries, ReviewRepository
from app.modules.reviews.domain.review import (
    COMPLETED,
    REVIEW_WINDOW,
    RemovalReason,
    ReplyStatus,
    Review,
    ReviewId,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, UserId
from app.platform.kernel.pagination import Page, PageRequest


class ReviewsFacade(ReviewsApi):
    def __init__(
        self,
        uow: UnitOfWork,
        reviews: ReviewRepository,
        ratings: RatingStore,
        queries: ReviewQueries,
        clock: Clock,
    ) -> None:
        self._uow, self._reviews, self._ratings = uow, reviews, ratings
        self._queries, self._clock = queries, clock

    async def summaries(self, profile_ids: Collection[UUID]) -> dict[UUID, RatingSummary]:
        return await self._ratings.summaries(profile_ids)

    async def reviews_of(self, profile_id: UUID, page: PageRequest) -> Page[PublicReview]:
        return await self._queries.public_of(profile_id, page)

    async def review_state(
        self,
        deal_id: DealId,
        viewer_id: UserId,
        *,
        client_id: UserId,
        status: str,
        completed_at: datetime | None,
    ) -> DealReviewState:
        mine = (await self._queries.mine(viewer_id, [deal_id])).get(deal_id)
        open_until = None
        if mine is None and viewer_id == client_id and status == COMPLETED and completed_at:
            until = completed_at + REVIEW_WINDOW
            open_until = until if until > self._clock.now() else None
        return DealReviewState(mine=mine, open_until=open_until)

    async def review_for_check(self, review_id: UUID) -> ReviewForCheck | None:
        review = await self._read(review_id)
        if review is None or not review.awaits_check:
            return None
        return ReviewForCheck(author_id=review.author_id, text=review.body or "")

    async def approve_review(self, review_id: UUID) -> None:
        review = await self._for_update(review_id)
        if review is not None and review.publish(now=self._clock.now()):
            await self._reviews.save(review)

    async def reject_review(
        self,
        review_id: UUID,
        *,
        reason_code: str,  # noqa: ARG002 — причина остаётся в кейсе модерации
    ) -> None:
        review = await self._for_update(review_id)
        if review is not None and review.remove(
            reason=RemovalReason.MODERATION, now=self._clock.now()
        ):
            await self._reviews.save(review)

    async def reply_for_check(self, review_id: UUID) -> ReviewForCheck | None:
        review = await self._read(review_id)
        reply = review.reply if review is not None else None
        if review is None or reply is None or reply.status is not ReplyStatus.UNDER_REVIEW:
            return None
        return ReviewForCheck(author_id=review.subject_user_id, text=reply.body)

    async def approve_reply(self, review_id: UUID) -> None:
        review = await self._for_update(review_id)
        if review is not None and review.publish_reply(now=self._clock.now()):
            await self._reviews.save(review)

    async def reject_reply(
        self,
        review_id: UUID,
        *,
        reason_code: str,  # noqa: ARG002 — причина остаётся в кейсе модерации
    ) -> None:
        review = await self._for_update(review_id)
        if review is not None and review.remove_reply(now=self._clock.now()):
            await self._reviews.save(review)

    async def _read(self, review_id: UUID) -> Review | None:
        """Отзыв для проверки — в своей транзакции (конвейер читает до своей)."""
        async with self._uow:
            return await self._reviews.find_for_update(ReviewId(review_id))

    async def _for_update(self, review_id: UUID) -> Review | None:
        self._uow.require_active()
        return await self._reviews.find_for_update(ReviewId(review_id))
