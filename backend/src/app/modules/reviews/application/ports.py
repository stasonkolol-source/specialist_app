"""Порты модуля reviews (ADR-0020 §3): чтение агрегатов рейтинга."""

from collections.abc import Collection
from typing import Protocol
from uuid import UUID

from app.modules.reviews.api import RatingSummary


class RatingAggregates(Protocol):
    async def summaries(self, profile_ids: Collection[UUID]) -> dict[UUID, RatingSummary]:
        """Строки агрегатов профилей; профиля без строки в ответе нет."""
        ...
