"""Ответить на отзыв (POST /reviews/{id}/reply, S28; DEVELOPMENT_PLAN 7.2): тот, о ком отзыв,
один раз и публично. Ответ ждёт автопроверки (цель `review_reply`) и виден после неё; второй
ответ — 409 `reply_exists`."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.api import Action, IdentityApi
from app.modules.reviews.application.ports import ReviewRepository
from app.modules.reviews.domain.review import Review, ReviewId
from app.platform.contracts.events.moderation import ModerationRequested
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId

REVIEW_REPLY = "review_reply"
"""`moderation.cases.entity_type` ответа на отзыв."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplyToReviewCommand:
    actor_id: UserId
    review_id: UUID
    body: str


class ReplyToReview:
    def __init__(
        self, uow: UnitOfWork, reviews: ReviewRepository, identity: IdentityApi, clock: Clock
    ) -> None:
        self._uow, self._reviews, self._identity, self._clock = uow, reviews, identity, clock

    async def __call__(self, cmd: ReplyToReviewCommand) -> Review:
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        async with self._uow:
            review = await self._reviews.get_for_update(ReviewId(cmd.review_id))
            now = self._clock.now()
            review.add_reply(author_id=cmd.actor_id, body=cmd.body, now=now)
            await self._reviews.save(review)
            self._uow.add_event(
                ModerationRequested(
                    entity_type=REVIEW_REPLY,
                    entity_id=review.id,
                    author_id=cmd.actor_id,
                    occurred_at=now,
                )
            )
        return review
