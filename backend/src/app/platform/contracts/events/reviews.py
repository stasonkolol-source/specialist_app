"""События модуля reviews (ADR-0020 §2; ARCHITECTURE §7.9; DEVELOPMENT_PLAN 7.2). Подписчики:
сам reviews (пересчёт рейтинга после публикации и снятия), поиск (рейтинг в выдаче —
`RatingChanged`), уведомления (`review.published`), аналитика."""

from dataclasses import dataclass
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewPublished(DomainEvent):
    """Отзыв прошёл проверку и виден на карточке специалиста (S08, S11)."""

    event_type = "reviews.ReviewPublished"
    review_id: UUID
    deal_id: DealId | None
    author_id: UserId
    subject_user_id: UserId
    subject_profile_id: UUID | None
    """Профиль, чей рейтинг меняется; None — у исполнителя нет профиля специалиста."""
    rating: int
    has_text: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewRemoved(DomainEvent):
    """Опубликованный отзыв снят (модерация, удаление аккаунта автора): рейтинг пересчитать."""

    event_type = "reviews.ReviewRemoved"
    review_id: UUID
    subject_user_id: UserId
    subject_profile_id: UUID | None
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RatingChanged(DomainEvent):
    """Рейтинг профиля пересчитан: поиск пересобирает строку выдачи (за секунды)."""

    event_type = "reviews.RatingChanged"
    profile_id: UUID
    rating_count: int
