"""Удалённый аккаунт (задача `reviews.forget_user` на UserDeleted; §7.10, ADR-0016): его отзывы
стираются и снимаются (ReviewRemoved → рейтинг пересчитается), его ответы на отзывы о нём
стираются, просьб об отзыве с ним больше нет."""

from dataclasses import dataclass

from app.modules.reviews.application.ports import ReviewRepository, ReviewRequests
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetUserReviewsCommand:
    user_id: UserId


class ForgetUserReviews:
    def __init__(
        self,
        uow: UnitOfWork,
        reviews: ReviewRepository,
        requests: ReviewRequests,
        clock: Clock,
    ) -> None:
        self._uow, self._reviews, self._requests, self._clock = uow, reviews, requests, clock

    async def __call__(self, cmd: ForgetUserReviewsCommand) -> None:
        now = self._clock.now()
        async with self._uow:
            for review_id in await self._reviews.written_by(cmd.user_id):
                review = await self._reviews.get_for_update(review_id)
                review.erase(now=now)
                await self._reviews.save(review)
            for review_id in await self._reviews.replied_by(cmd.user_id):
                review = await self._reviews.get_for_update(review_id)
                review.erase_reply(now=now)
                await self._reviews.save(review)
            await self._requests.forget(cmd.user_id)
