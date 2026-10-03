"""Оставить отзыв (POST /deals/{id}/review, S27; DEVELOPMENT_PLAN 7.2): клиент по завершённой
сделке, не позже 14 дней после завершения, один раз. Отзыв ждёт автопроверки
(ModerationRequested → адаптер цели `review`) и публикуется после неё."""

from dataclasses import dataclass, field

from app.modules.deals.api import DealsApi
from app.modules.identity.api import Action, IdentityApi
from app.modules.reviews.application.ports import ReviewRepository
from app.modules.reviews.domain.review import DealFacts, Review, ReviewId
from app.modules.reviews.errors import ReviewExistsError
from app.platform.contracts.events.moderation import ModerationRequested
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, UserId, new_id

REVIEW = "review"
"""`moderation.cases.entity_type` отзыва."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LeaveReviewCommand:
    actor_id: UserId
    deal_id: DealId
    rating: int
    criteria: dict[str, int] = field(default_factory=dict)
    body: str | None = None


class LeaveReview:
    def __init__(
        self,
        uow: UnitOfWork,
        reviews: ReviewRepository,
        deals: DealsApi,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._reviews, self._deals = uow, reviews, deals
        self._identity, self._clock = identity, clock

    async def __call__(self, cmd: LeaveReviewCommand) -> Review:
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        async with self._uow:
            deal = await self._deals.deal_for(cmd.deal_id, cmd.actor_id)
            existing = await self._reviews.of_deal(cmd.deal_id, cmd.actor_id)
            if existing is not None:
                raise ReviewExistsError(review_id=str(existing))
            review = Review.for_deal(
                review_id=ReviewId(new_id()),
                deal=DealFacts(
                    id=deal.id,
                    client_id=deal.client_id,
                    performer_id=deal.performer_id,
                    profile_id=deal.profile_id,
                    category_id=deal.category_id,
                    status=deal.status,
                    completed_at=deal.completed_at,
                ),
                author_id=cmd.actor_id,
                rating=cmd.rating,
                criteria=cmd.criteria,
                body=cmd.body,
                now=self._clock.now(),
            )
            await self._reviews.add(review)
            self._uow.add_event(
                ModerationRequested(
                    entity_type=REVIEW,
                    entity_id=review.id,
                    author_id=review.author_id,
                    occurred_at=review.created_at,
                )
            )
        return review
