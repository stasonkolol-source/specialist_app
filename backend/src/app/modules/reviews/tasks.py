"""Задачи reviews (ADR-0020 §3).

- `reviews.recompute_on_published` — ReviewPublished: пересчитать рейтинг профиля; изменился —
  RatingChanged, поиск обновит выдачу (DEVELOPMENT_PLAN 7.2);
- `reviews.recompute_on_removed` — ReviewRemoved: то же после снятия опубликованного отзыва.
"""

from uuid import UUID

from dishka import FromDishka

from app.modules.reviews.application.ports import RECOMPUTE_ON_PUBLISHED, RECOMPUTE_ON_REMOVED
from app.modules.reviews.application.use_cases.recompute_rating import (
    RecomputeRating,
    RecomputeRatingCommand,
)
from app.platform.contracts.events.reviews import ReviewPublished, ReviewRemoved
from app.platform.queue.tasks import subscriber


async def _recompute(recompute: RecomputeRating, profile_id: UUID | None) -> None:
    if profile_id is not None:
        await recompute(RecomputeRatingCommand(profile_id=profile_id))


@subscriber(ReviewPublished, RECOMPUTE_ON_PUBLISHED)
async def recompute_on_published(
    event: ReviewPublished, recompute: FromDishka[RecomputeRating]
) -> None:
    await _recompute(recompute, event.subject_profile_id)


@subscriber(ReviewRemoved, RECOMPUTE_ON_REMOVED)
async def recompute_on_removed(
    event: ReviewRemoved, recompute: FromDishka[RecomputeRating]
) -> None:
    await _recompute(recompute, event.subject_profile_id)
