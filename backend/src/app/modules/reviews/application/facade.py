"""Реализация ReviewsApi (ADR-0020 §6): рейтинг профилей для карточки и выдачи.

Агрегаты пересчитывают отзывы по сделкам (7.2); до того их нет — «Новый специалист».
"""

from collections.abc import Collection
from uuid import UUID

from app.modules.reviews.api import RatingSummary, ReviewsApi
from app.modules.reviews.application.ports import RatingAggregates


class ReviewsFacade(ReviewsApi):
    def __init__(self, aggregates: RatingAggregates) -> None:
        self._aggregates = aggregates

    async def summaries(self, profile_ids: Collection[UUID]) -> dict[UUID, RatingSummary]:
        return await self._aggregates.summaries(profile_ids)
