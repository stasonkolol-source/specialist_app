"""Схемы HTTP reviews (ARCHITECTURE §8.5): отзыв по сделке (S27), ответ (S28), «Мои отзывы»."""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.reviews.application.dto import UserReview
from app.modules.reviews.domain.review import (
    MAX_BODY,
    MAX_REPLY,
    STARS,
    Criterion,
    ReplyStatus,
    Review,
    ReviewStatus,
)
from app.platform.kernel.ids import DealId, UserId

Stars = Annotated[int, Field(ge=1, le=STARS)]


class ReviewIn(BaseModel):
    rating: Stars = Field(description="Оценка 1–5")
    criteria: dict[Criterion, Stars] = Field(
        default_factory=dict,
        description="По желанию: качество, пунктуальность, общение, соответствие цене — 1–5",
    )
    body: str | None = Field(default=None, max_length=MAX_BODY, description="Текст, до 2000")


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_REPLY)


class ReplyOut(BaseModel):
    body: str
    at: datetime
    status: str = Field(description="under_review | published | removed")


class ReviewOut(BaseModel):
    """Отзыв автору или тому, о ком он: с ответом в любом статусе."""

    id: UUID
    deal_id: UUID | None
    rating: int
    criteria: dict[str, int]
    body: str | None
    status: str = Field(description="under_review | published | removed")
    created_at: datetime
    published_at: datetime | None
    reply: ReplyOut | None

    @classmethod
    def of(cls, review: Review) -> ReviewOut:
        reply = review.reply
        return cls(
            id=review.id,
            deal_id=review.deal_id,
            rating=review.rating,
            criteria={criterion.value: value for criterion, value in review.criteria.items()},
            body=review.body,
            status=review.status.value,
            created_at=review.created_at,
            published_at=review.published_at,
            reply=(
                ReplyOut(body=reply.body, at=reply.at, status=reply.status.value)
                if reply is not None
                else None
            ),
        )


class MyReviewOut(BaseModel):
    """Отзыв в «Моих отзывах» (S28)."""

    id: UUID
    deal_id: UUID | None
    deal_title: str | None
    counterpart_name: str | None = Field(
        description="Автор (полученные) или тот, о ком отзыв (написанные); удалён — null"
    )
    rating: int
    criteria: dict[str, int]
    body: str | None
    status: str = Field(description="under_review | published | removed")
    created_at: datetime
    published_at: datetime | None
    reply: ReplyOut | None = Field(
        description="Полученные — свой ответ в любом статусе; написанные — только опубликованный"
    )
    can_reply: bool = Field(description="Полученный опубликованный отзыв без ответа")


class MyReviewsPageOut(BaseModel):
    items: list[MyReviewOut]
    next_cursor: str | None


def my_review_out(
    item: UserReview,
    *,
    received: bool,
    names: Mapping[UserId, str],
    titles: Mapping[DealId, str],
) -> MyReviewOut:
    reply = None
    shown = received or item.reply_status == ReplyStatus.PUBLISHED.value
    if shown and item.reply_body is not None and item.reply_at is not None:
        reply = ReplyOut(body=item.reply_body, at=item.reply_at, status=item.reply_status or "")
    return MyReviewOut(
        id=item.id,
        deal_id=item.deal_id,
        deal_title=titles.get(item.deal_id) if item.deal_id is not None else None,
        counterpart_name=names.get(item.counterpart_id),
        rating=item.rating,
        criteria=dict(item.criteria),
        body=item.body,
        status=item.status,
        created_at=item.created_at,
        published_at=item.published_at,
        reply=reply,
        can_reply=(
            received and item.status == ReviewStatus.PUBLISHED.value and item.reply_status is None
        ),
    )
