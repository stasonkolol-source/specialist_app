"""Порты модуля reviews (ADR-0020 §1, §3): отзывы, рейтинг профилей, чтение для экранов, задачи."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from app.modules.reviews.api import MyReview, PublicReview, RatingSummary
from app.modules.reviews.application.dto import ReviewsDirection, UserReview
from app.modules.reviews.domain.rating import CategoryStats, Rated, Rating
from app.modules.reviews.domain.request import RequestStage
from app.modules.reviews.domain.review import Review, ReviewId
from app.platform.contracts.events.deals import DealCompleted
from app.platform.contracts.events.identity import UserDeleted
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

    async def written_by(self, user_id: UserId) -> list[ReviewId]:
        """Не стёртые отзывы автора: удаление аккаунта стирает их."""
        ...

    async def replied_by(self, user_id: UserId) -> list[ReviewId]:
        """Отзывы, на которые человек ответил: удаление аккаунта стирает ответы."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class OpenRequest:
    """Просьба об отзыве без отзыва в окне: пора ли напомнить, решает domain/request.py."""

    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    completed_at: datetime
    reminded_at: datetime | None
    last_call_at: datetime | None


class ReviewRequests(Protocol):
    async def open(
        self, *, deal_id: DealId, client_id: UserId, performer_id: UserId, completed_at: datetime
    ) -> bool:
        """Записать просьбу по сделке; уже есть — False (повтор задачи)."""
        ...

    async def awaiting(self, now: datetime, *, limit: int) -> list[OpenRequest]:
        """Просьбы, по которым ещё может понадобиться напоминание: окно открыто, прошли сутки,
        последнего напоминания не было, отзыва клиента по сделке нет."""
        ...

    async def mark(self, deal_id: DealId, stage: RequestStage, at: datetime) -> None: ...

    async def forget(self, user_id: UserId) -> None:
        """Удалённый аккаунт: его просьб (как клиента и как исполнителя) больше нет."""
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

    async def rated_profiles(self) -> list[UUID]:
        """Профили со строкой рейтинга: ночной пересчёт (затухание и средние категорий)."""
        ...


class ReviewQueries(Protocol):
    async def public_of(self, profile_id: UUID, page: PageRequest) -> Page[PublicReview]:
        """Опубликованные отзывы профиля, новые первыми; ответ — только прошедший проверку."""
        ...

    async def public(self, review_id: UUID) -> PublicReview | None:
        """Один опубликованный (не стёртый) отзыв."""
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
OPEN_REQUEST: Final = TaskRef("reviews.open_request", DealCompleted)
"""Сделка завершена — попросить клиента об отзыве (`review.request`)."""
FORGET_USER: Final = TaskRef("reviews.forget_user", UserDeleted)
"""Аккаунт удалён — его отзывы и ответы стираются, рейтинги пересчитываются."""
