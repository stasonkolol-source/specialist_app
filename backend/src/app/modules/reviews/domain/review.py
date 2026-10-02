"""Отзыв (DEVELOPMENT_PLAN 7.2; ARCHITECTURE §7.9, ADR-0016): клиент о исполнителе по сделке.

- оставляет только клиент (v1 — и исполнитель о клиенте, double-blind), только по сделке
  `completed` и не позже 14 дней после завершения; один отзыв на сделку, не редактируется;
- оценка 1–5, критерии (качество, пунктуальность, общение, соответствие цене) — по желанию,
  текст до 2000 символов (фото — v1);
- `under_review` → `published` после автопроверок (адаптер цели `review`), при флаге — после
  модератора; нарушение — `removed`. Рейтинг считают только опубликованные;
- исполнитель один раз отвечает публично; ответ проходит ту же проверку (цель `review_reply`)
  и виден после неё;
- удаление аккаунта автора стирает его отзывы, удаление аккаунта исполнителя — его ответы.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, NewType
from uuid import UUID

from app.modules.reviews.errors import (
    InvalidReviewError,
    NotReviewSubjectError,
    ReplyExistsError,
    ReviewNotAllowedError,
    ReviewNotFoundError,
)
from app.platform.contracts.events.reviews import ReviewPublished, ReviewRemoved
from app.platform.kernel.aggregate import VersionedAggregate
from app.platform.kernel.ids import CategoryId, DealId, UserId

ReviewId = NewType("ReviewId", UUID)

REVIEW_WINDOW: Final = timedelta(days=14)
"""Отзыв — не позже 14 дней после завершения сделки (§7.9)."""
MAX_BODY: Final = 2000
MAX_REPLY: Final = 2000
STARS: Final = 5
COMPLETED = "completed"
"""DealStatus сделки, по которой можно оставить отзыв."""


class ReviewKind(StrEnum):
    DEAL = "deal"
    PRE_PLATFORM = "pre_platform"
    """«Отзыв до платформы» по приглашению (7.6): в рейтинг не входит."""


class ReviewDirection(StrEnum):
    CLIENT_TO_PERFORMER = "client_to_performer"
    PERFORMER_TO_CLIENT = "performer_to_client"
    """v1: оценка клиента исполнителем."""


class ReviewStatus(StrEnum):
    HIDDEN = "hidden"
    """v1: double-blind — до отзыва второй стороны или конца окна."""
    UNDER_REVIEW = "under_review"
    PUBLISHED = "published"
    REMOVED = "removed"


class ReplyStatus(StrEnum):
    UNDER_REVIEW = "under_review"
    PUBLISHED = "published"
    REMOVED = "removed"


class Criterion(StrEnum):
    QUALITY = "quality"
    PUNCTUALITY = "punctuality"
    COMMUNICATION = "communication"
    PRICE = "price"
    """Соответствие цене."""


class RemovalReason(StrEnum):
    MODERATION = "moderation"
    AUTHOR_DELETED = "author_deleted"


@dataclass(frozen=True, slots=True, kw_only=True)
class DealFacts:
    """Что отзыву нужно знать о сделке (фасад deals): стороны, статус, когда завершена."""

    id: DealId
    client_id: UserId
    performer_id: UserId
    profile_id: UUID | None
    category_id: CategoryId | None
    status: str
    completed_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Reply:
    body: str
    at: datetime
    status: ReplyStatus


@dataclass(eq=False, kw_only=True)
class Review(VersionedAggregate):
    id: ReviewId
    kind: ReviewKind
    deal_id: DealId | None
    author_id: UserId
    subject_user_id: UserId
    subject_profile_id: UUID | None
    category_id: CategoryId | None
    """Категория сделки: среднее по категории — априорное в байесовском рейтинге."""
    direction: ReviewDirection
    rating: int
    criteria: dict[Criterion, int] = field(default_factory=dict)
    body: str | None
    status: ReviewStatus
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    reply: Reply | None = None
    deleted_at: datetime | None = None

    @classmethod
    def for_deal(
        cls,
        *,
        review_id: ReviewId,
        deal: DealFacts,
        author_id: UserId,
        rating: int,
        criteria: dict[str, int],
        body: str | None,
        now: datetime,
    ) -> Review:
        """Отзыв клиента по завершённой сделке: ждёт автопроверки."""
        if author_id != deal.client_id:
            raise ReviewNotAllowedError(deal_id=deal.id, reason="not_client")
        if deal.status != COMPLETED or deal.completed_at is None:
            raise ReviewNotAllowedError(deal_id=deal.id, reason="not_completed")
        if now > deal.completed_at + REVIEW_WINDOW:
            raise ReviewNotAllowedError(deal_id=deal.id, reason="window_closed")
        return cls(
            id=review_id,
            kind=ReviewKind.DEAL,
            deal_id=deal.id,
            author_id=author_id,
            subject_user_id=deal.performer_id,
            subject_profile_id=deal.profile_id,
            category_id=deal.category_id,
            direction=ReviewDirection.CLIENT_TO_PERFORMER,
            rating=_stars(rating, "rating"),
            criteria=_criteria(criteria),
            body=_text(body, field="body", limit=MAX_BODY),
            status=ReviewStatus.UNDER_REVIEW,
            created_at=now,
            updated_at=now,
            version=1,
        )

    @property
    def awaits_check(self) -> bool:
        """Ждёт автопроверки или модератора."""
        return self.status is ReviewStatus.UNDER_REVIEW and self.deleted_at is None

    @property
    def visible(self) -> bool:
        """Опубликован и не стёрт: виден на карточке и считается в рейтинге."""
        return self.status is ReviewStatus.PUBLISHED and self.deleted_at is None

    def publish(self, *, now: datetime) -> bool:
        """Проверка пройдена: «на проверке» → «опубликован». Другой статус — ничего (False)."""
        if not self.awaits_check:
            return False
        self.status = ReviewStatus.PUBLISHED
        self.published_at = self.updated_at = now
        self._record(
            ReviewPublished(
                review_id=self.id,
                deal_id=self.deal_id,
                author_id=self.author_id,
                subject_user_id=self.subject_user_id,
                subject_profile_id=self.subject_profile_id,
                rating=self.rating,
                has_text=self.body is not None,
                occurred_at=now,
            )
        )
        return True

    def remove(self, *, reason: RemovalReason, now: datetime) -> bool:
        """Снять отзыв: модерация нашла нарушение. Снятый опубликованный меняет рейтинг."""
        if self.status not in (ReviewStatus.UNDER_REVIEW, ReviewStatus.PUBLISHED):
            return False
        was_visible = self.visible
        self.status = ReviewStatus.REMOVED
        self.updated_at = now
        if was_visible:
            self._record(
                ReviewRemoved(
                    review_id=self.id,
                    subject_user_id=self.subject_user_id,
                    subject_profile_id=self.subject_profile_id,
                    reason=reason.value,
                    occurred_at=now,
                )
            )
        return True

    def erase(self, *, now: datetime) -> None:
        """Аккаунт автора удалён: текст и критерии стираются, отзыв снят (§7.10, ADR-0016)."""
        if self.deleted_at is not None:
            return
        self.remove(reason=RemovalReason.AUTHOR_DELETED, now=now)
        self.body = None
        self.criteria = {}
        self.deleted_at = self.updated_at = now

    def add_reply(self, *, author_id: UserId, body: str, now: datetime) -> None:
        """Ответ того, о ком отзыв: один, на опубликованный отзыв, ждёт проверки."""
        if not self.visible:
            raise ReviewNotFoundError(review_id=self.id)
        if author_id != self.subject_user_id:
            raise NotReviewSubjectError(review_id=self.id)
        if self.reply is not None:
            raise ReplyExistsError(review_id=self.id)
        text = _text(body, field="reply", limit=MAX_REPLY)
        if text is None:
            raise InvalidReviewError(field="reply", reason="empty")
        self.reply = Reply(body=text, at=now, status=ReplyStatus.UNDER_REVIEW)
        self.updated_at = now

    def publish_reply(self, *, now: datetime) -> bool:
        if self.reply is None or self.reply.status is not ReplyStatus.UNDER_REVIEW:
            return False
        self.reply = Reply(body=self.reply.body, at=self.reply.at, status=ReplyStatus.PUBLISHED)
        self.updated_at = now
        return True

    def remove_reply(self, *, now: datetime) -> bool:
        """Нарушение в ответе: ответ скрыт, отзыв остаётся. Второго ответа не будет."""
        if self.reply is None or self.reply.status is ReplyStatus.REMOVED:
            return False
        self.reply = Reply(body=self.reply.body, at=self.reply.at, status=ReplyStatus.REMOVED)
        self.updated_at = now
        return True

    def erase_reply(self, *, now: datetime) -> None:
        """Аккаунт исполнителя удалён: его ответ стирается."""
        if self.reply is not None:
            self.reply = None
            self.updated_at = now


def _stars(value: int, name: str) -> int:
    if isinstance(value, bool) or not 1 <= value <= STARS:
        raise InvalidReviewError(field=name, reason="range")
    return value


def _criteria(raw: dict[str, int]) -> dict[Criterion, int]:
    criteria: dict[Criterion, int] = {}
    for name, value in raw.items():
        try:
            criterion = Criterion(name)
        except ValueError:
            raise InvalidReviewError(field="criteria", reason="unknown") from None
        criteria[criterion] = _stars(value, "criteria")
    return criteria


def _text(value: str | None, *, field: str, limit: int) -> str | None:
    """Текст без пробелов по краям; пустой — None."""
    text = (value or "").strip()
    if not text:
        return None
    if len(text) > limit:
        raise InvalidReviewError(field=field, reason="length")
    return text
