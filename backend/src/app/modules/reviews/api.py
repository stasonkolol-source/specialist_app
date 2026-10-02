"""Контракт модуля reviews для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из reviews только этот файл.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from app.platform.kernel.ids import DealId, UserId
from app.platform.kernel.pagination import Page, PageRequest

NEW_UNTIL_REVIEWS: Final = 3
"""«Новый специалист» — пока отзывов по сделкам меньше трёх (ARCHITECTURE §9.4)."""
NO_REVIEWS_LOWER_BOUND: Final = 2.05
"""Нижняя граница рейтинга профиля без отзывов (только априорное распределение): ранжирование
ставит такой профиль выше профиля с одной «единицей» и ниже профиля с одной «пятёркой».
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class RatingSummary:
    """Рейтинг профиля по отзывам сделок; «до платформы» в него не входят (ADR-0016)."""

    count: int
    average: float
    """Для показа и фильтра «рейтинг от» — байесовское среднее: «4,9»."""
    lower_bound: float = NO_REVIEWS_LOWER_BOUND
    """Нижняя граница доверительного интервала — ранжирование в поиске."""
    distribution: tuple[int, ...]
    """Сколько оценок в 1, 2, 3, 4 и 5 звёзд — гистограмма S11."""
    criteria: Mapping[str, float] = field(default_factory=dict)
    """Средние по критериям: quality, punctuality, communication, price."""
    last_published_at: datetime | None = None

    @property
    def is_new(self) -> bool:
        return self.count < NEW_UNTIL_REVIEWS


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplyView:
    """Публичный ответ исполнителя на отзыв (прошёл проверку)."""

    body: str
    at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class PublicReview:
    """Опубликованный отзыв на карточке специалиста (S08, S11)."""

    id: UUID
    kind: str
    """ReviewKind: `deal` или `pre_platform` (7.6)."""
    author_id: UserId
    subject_profile_id: UUID | None
    rating: int
    criteria: Mapping[str, int]
    body: str | None
    category_id: int | None
    published_at: datetime
    reply: ReplyView | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MyReview:
    """Свой отзыв по сделке — карточка сделки S26 и S27: что уже оставлено и в каком статусе."""

    id: UUID
    status: str
    """ReviewStatus: `under_review`, `published`, `removed`."""
    rating: int


@dataclass(frozen=True, slots=True, kw_only=True)
class DealReviewState:
    """Отзыв по сделке глазами стороны (S26, S27): свой уже оставлен или до когда можно."""

    mine: MyReview | None
    open_until: datetime | None
    """Клиент может оставить отзыв до этого времени (14 дней после завершения); None — нельзя
    или уже оставлен."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewForCheck:
    """Что проверять модерации (адаптеры целей `review` и `review_reply`): отзыв и ответ не
    редактируются, поэтому версии у проверки нет."""

    author_id: UserId
    text: str


class ReviewsApi(Protocol):
    async def summaries(self, profile_ids: Collection[UUID]) -> dict[UUID, RatingSummary]:
        """Рейтинг профилей; профиль без отзывов по сделкам в ответ не попадает."""
        ...

    async def reviews_of(self, profile_id: UUID, page: PageRequest) -> Page[PublicReview]:
        """Опубликованные отзывы профиля, новые первыми (S11; первый — на S08)."""
        ...

    async def review_state(
        self,
        deal_id: DealId,
        viewer_id: UserId,
        *,
        client_id: UserId,
        status: str,
        completed_at: datetime | None,
    ) -> DealReviewState:
        """Отзыв стороны по сделке: свой (не стёртый) и срок, до которого клиент может его
        оставить (по сделке `completed`, 14 дней после завершения)."""
        ...

    async def review_for_check(self, review_id: UUID) -> ReviewForCheck | None:
        """Текст отзыва, который ждёт проверки; None — отзыва нет или он уже не ждёт."""
        ...

    async def approve_review(self, review_id: UUID) -> None:
        """Проверка пройдена: отзыв опубликован (в транзакции вызывающего)."""
        ...

    async def reject_review(self, review_id: UUID, *, reason_code: str) -> None:
        """Нарушение: отзыв снят (в транзакции вызывающего)."""
        ...

    async def reply_for_check(self, review_id: UUID) -> ReviewForCheck | None:
        """Ответ исполнителя, который ждёт проверки; None — нет такого."""
        ...

    async def approve_reply(self, review_id: UUID) -> None:
        """Ответ прошёл проверку и виден (в транзакции вызывающего)."""
        ...

    async def reject_reply(self, review_id: UUID, *, reason_code: str) -> None:
        """Нарушение в ответе: ответ скрыт, отзыв остаётся (в транзакции вызывающего)."""
        ...
