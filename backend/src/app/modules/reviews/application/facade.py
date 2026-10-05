"""Реализация ReviewsApi (ADR-0020 §6): рейтинг и отзывы для карточки специалиста, выдачи и
сделки; проверка отзывов и ответов для модерации (адаптеры целей `review` и `review_reply`).

Методы проверки, которые меняют отзыв, идут в транзакции вызывающего (модерация публикует или
снимает объект вместе со своим кейсом); чтение текста для проверки — в своей.
"""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from app.modules.reviews.api import (
    DEAL,
    DealRef,
    DealReviewState,
    InviteRef,
    PublicReview,
    RatingSummary,
    ReviewForCheck,
    ReviewsApi,
)
from app.modules.reviews.application.ports import (
    RatingStore,
    ReviewInvites,
    ReviewQueries,
    ReviewRepository,
)
from app.modules.reviews.domain.review import (
    COMPLETED,
    REVIEW_WINDOW,
    RemovalReason,
    ReplyStatus,
    Review,
    ReviewId,
    ReviewKind,
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
        invites: ReviewInvites,
        clock: Clock,
    ) -> None:
        self._uow, self._reviews, self._ratings = uow, reviews, ratings
        self._queries, self._invites, self._clock = queries, invites, clock

    async def summaries(self, profile_ids: Collection[UUID]) -> dict[UUID, RatingSummary]:
        return await self._ratings.summaries(profile_ids)

    async def reviews_of(
        self, profile_id: UUID, page: PageRequest, *, kind: str = DEAL
    ) -> Page[PublicReview]:
        return await self._queries.public_of(profile_id, page, ReviewKind(kind))

    async def review_count(self, profile_id: UUID, *, kind: str) -> int:
        return await self._queries.count_of(profile_id, ReviewKind(kind))

    async def open_invite(self, token: UUID) -> InviteRef | None:
        invite = await self._invites.find(token)
        if invite is None or not invite.usable(self._clock.now()):
            return None
        return InviteRef(profile_id=invite.profile_id, expires_at=invite.expires_at)

    async def published_review(self, review_id: UUID) -> PublicReview | None:
        return await self._queries.public(review_id)

    async def review_state(
        self,
        deal_id: DealId,
        viewer_id: UserId,
        *,
        client_id: UserId,
        status: str,
        completed_at: datetime | None,
    ) -> DealReviewState:
        ref = DealRef(id=deal_id, client_id=client_id, status=status, completed_at=completed_at)
        return (await self.review_states(viewer_id, [ref]))[deal_id]

    async def review_states(
        self, viewer_id: UserId, deals: Collection[DealRef]
    ) -> dict[DealId, DealReviewState]:
        mine = await self._queries.mine(viewer_id, [deal.id for deal in deals])
        now = self._clock.now()
        states: dict[DealId, DealReviewState] = {}
        for deal in deals:
            own = mine.get(deal.id)
            open_until = None
            if own is None and viewer_id == deal.client_id and deal.status == COMPLETED:
                until = deal.completed_at + REVIEW_WINDOW if deal.completed_at else None
                open_until = until if until is not None and until > now else None
            states[deal.id] = DealReviewState(mine=own, open_until=open_until)
        return states

    async def review_for_check(self, review_id: UUID) -> ReviewForCheck | None:
        review = await self._read(review_id)
        if review is None or not review.awaits_check:
            return None
        # до платформы: «что делал мастер» проверяется вместе с текстом, и всегда — человеком
        text = "\n".join(part for part in (review.work_title, review.body) if part)
        return ReviewForCheck(
            author_id=review.author_id,
            text=text,
            always_review=not review.rated,
            rating=review.rating,
        )

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
