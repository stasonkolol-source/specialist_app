"""Порты модуля reviews (ADR-0020 §1, §3): отзывы, рейтинг профилей, чтение для экранов, задачи."""

from collections.abc import Collection
from typing import Final, Protocol
from uuid import UUID

from app.modules.reviews.api import MyReview, PublicReview, RatingSummary
from app.modules.reviews.application.dto import ReviewsDirection, UserReview
from app.modules.reviews.domain.rating import CategoryStats, Rated, Rating
from app.modules.reviews.domain.review import Review, ReviewId
from app.platform.contracts.events.reviews import ReviewPublished, ReviewRemoved
from app.platform.kernel.ids import DealId, UserId
from app.platform.kernel.pagination import Page, PageRequest
from app.platform.queue.port import TaskRef


class ReviewRepository(Protocol):
    async def add(self, review: Review) -> None:
        """Записать новый отзыв; второй отзыв автора по сделке — ReviewExistsError."""
        ...

    async def get_for_update(self, review_id: ReviewId) -> Review:
        """Отзыв под блокировкой строки; нет — ReviewNotFoundError."""
        ...

    async def find_for_update(self, review_id: ReviewId) -> Review | None: ...

    async def save(self, review: Review) -> None: ...

    async def of_deal(self, deal_id: DealId, author_id: UserId) -> ReviewId | None:
        """Отзыв автора по сделке (не стёртый)."""
        ...


class RatingStore(Protocol):
    """Рейтинг профилей: агрегаты (`reviews.rating_aggregates`) и данные для пересчёта."""

    async def summaries(self, profile_ids: Collection[UUID]) -> dict[UUID, RatingSummary]:
        """Строки агрегатов профилей; профиля без строки в ответе нет."""
        ...

    async def lock(self, profile_id: UUID) -> None:
        """Advisory lock профиля до конца транзакции: пересчёты одного профиля идут по очереди и
        видят все закоммиченные отзывы."""
        ...

    async def published_of(self, profile_id: UUID) -> list[Rated]:
        """Опубликованные отзывы профиля по сделкам — то, что считает рейтинг."""
        ...

    async def category_stats(self) -> dict[int | None, CategoryStats]:
        """Опубликованные отзывы по категориям сделок: число и сумма оценок."""
        ...

    async def store(self, profile_id: UUID, rating: Rating | None) -> bool:
        """Записать рейтинг (None — отзывов нет, строка удаляется). True — что-то изменилось."""
        ...


class ReviewQueries(Protocol):
    async def public_of(self, profile_id: UUID, page: PageRequest) -> Page[PublicReview]:
        """Опубликованные отзывы профиля, новые первыми; ответ — только прошедший проверку."""
        ...

    async def mine(self, author_id: UserId, deal_ids: Collection[DealId]) -> dict[DealId, MyReview]:
        """Свои не стёртые отзывы по этим сделкам."""
        ...

    async def of_user(
        self, user_id: UserId, direction: ReviewsDirection, page: PageRequest
    ) -> Page[UserReview]:
        """«Мои отзывы» (S28): полученные — опубликованные обо мне, написанные — мои."""
        ...


RECOMPUTE_ON_PUBLISHED: Final = TaskRef("reviews.recompute_on_published", ReviewPublished)
"""Опубликован отзыв — пересчитать рейтинг профиля (→ RatingChanged → поиск)."""
RECOMPUTE_ON_REMOVED: Final = TaskRef("reviews.recompute_on_removed", ReviewRemoved)
"""Снят опубликованный отзыв — пересчитать рейтинг профиля."""
