"""Контракт модуля reviews для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из reviews только этот файл.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol
from uuid import UUID

NEW_UNTIL_REVIEWS: Final = 3
"""«Новый специалист» — пока отзывов по сделкам меньше трёх (ARCHITECTURE §9.4)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RatingSummary:
    """Рейтинг профиля по отзывам сделок; «до платформы» в него не входят (ADR-0016)."""

    count: int
    average: float
    """Среднее для показа: «4,9»."""
    distribution: tuple[int, ...]
    """Сколько оценок в 1, 2, 3, 4 и 5 звёзд — гистограмма S11."""
    criteria: Mapping[str, float] = field(default_factory=dict)
    """Средние по критериям: quality, punctuality, communication, price."""

    @property
    def is_new(self) -> bool:
        return self.count < NEW_UNTIL_REVIEWS


class ReviewsApi(Protocol):
    async def summaries(self, profile_ids: Collection[UUID]) -> dict[UUID, RatingSummary]:
        """Рейтинг профилей; профиль без отзывов по сделкам в ответ не попадает."""
        ...
