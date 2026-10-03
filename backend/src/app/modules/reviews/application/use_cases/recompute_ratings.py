"""Пересчитать все рейтинги (periodic `reviews.recompute_ratings`, ночью; ADR-0016): вес отзыва
со временем падает (half-life 12 месяцев), средние категорий меняются — рейтинг каждого профиля
с отзывами пересчитывается по одному, изменившийся — RatingChanged."""

from dataclasses import dataclass

from app.modules.reviews.application.ports import RatingStore
from app.modules.reviews.application.use_cases.recompute_rating import (
    RecomputeRating,
    RecomputeRatingCommand,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class RecomputeRatingsCommand:
    pass


class RecomputeRatings:
    def __init__(self, ratings: RatingStore, recompute: RecomputeRating) -> None:
        self._ratings, self._recompute = ratings, recompute

    async def __call__(self, cmd: RecomputeRatingsCommand) -> int:  # noqa: ARG002 — без параметров
        """Сколько рейтингов изменилось."""
        changed = 0
        for profile_id in await self._ratings.rated_profiles():
            changed += await self._recompute(RecomputeRatingCommand(profile_id=profile_id))
        return changed
