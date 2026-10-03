"""Пересчитать рейтинг профиля (задачи `reviews.recompute_on_*`; DEVELOPMENT_PLAN 7.2): после
публикации или снятия отзыва — по всем его опубликованным отзывам заново (формулы —
domain/rating.py). Пересчёты одного профиля идут по очереди (advisory lock) и видят все
закоммиченные отзывы. Изменился рейтинг — RatingChanged: поиск пересобирает строку выдачи."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.reviews.application.ports import RatingStore
from app.modules.reviews.domain.rating import rate
from app.platform.contracts.events.reviews import RatingChanged
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class RecomputeRatingCommand:
    profile_id: UUID


class RecomputeRating:
    def __init__(self, uow: UnitOfWork, ratings: RatingStore, clock: Clock) -> None:
        self._uow, self._ratings, self._clock = uow, ratings, clock

    async def __call__(self, cmd: RecomputeRatingCommand) -> bool:
        """True — рейтинг изменился."""
        async with self._uow:
            await self._ratings.lock(cmd.profile_id)
            reviews = await self._ratings.published_of(cmd.profile_id)
            categories = await self._ratings.category_stats() if reviews else {}
            now = self._clock.now()
            rating = rate(reviews, categories=categories, now=now)
            changed = await self._ratings.store(cmd.profile_id, rating)
            if changed:
                self._uow.add_event(
                    RatingChanged(
                        profile_id=cmd.profile_id,
                        rating_count=rating.count if rating is not None else 0,
                        occurred_at=now,
                    )
                )
        return changed
