"""Схемы HTTP reviews (ARCHITECTURE §8.5): отзыв по сделке (S27), ответ (S28), «Мои отзывы»,
приглашения на «отзыв до платформы» (S55) и отзыв по приглашению (S56)."""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.reviews.application.dto import UserReview
from app.modules.reviews.application.use_cases.list_review_invites import InviteItem
from app.modules.reviews.domain.invite import MAX_CLIENT_NAME, MAX_INVITES
from app.modules.reviews.domain.review import (
    MAX_BODY,
    MAX_REPLY,
    MAX_WORK_TITLE,
    STARS,
    Criterion,
    ReplyStatus,
    Review,
    ReviewStatus,
)
from app.platform.kernel.ids import DealId, UserId
from app.platform.text.names import short_name

Stars = Annotated[int, Field(ge=1, le=STARS)]


class ReviewIn(BaseModel):
    rating: Stars = Field(description="Оценка 1–5")
    criteria: dict[Criterion, Stars] = Field(
        default_factory=dict,
        description="По желанию: качество, пунктуальность, общение, соответствие цене — 1–5",
    )
    body: str | None = Field(default=None, max_length=MAX_BODY, description="Текст, до 2000")


class InviteReviewIn(BaseModel):
    """«Отзыв до платформы» по приглашению (S56): без критериев — их у прошлой работы не было."""

    rating: Stars = Field(description="Оценка 1–5")
    work_title: str | None = Field(
        default=None, max_length=MAX_WORK_TITLE, description="«Что делал мастер», до 120"
    )
    body: str | None = Field(default=None, max_length=MAX_BODY, description="Текст, до 2000")
    confirmed: Literal[True] = Field(
        description="Галочка «Подтверждаю…» — только true"
    )


class ReviewInviteIn(BaseModel):
    client_name: str | None = Field(
        default=None,
        max_length=MAX_CLIENT_NAME,
        description="Кому отправлена ссылка — заметка для себя в списке S55, по желанию",
    )


class ReviewInviteOut(BaseModel):
    """Приглашение в списке S55."""

    token: UUID = Field(description="Секрет ссылки: путь /review-invites/{token} и отзыв ссылки")
    url: str = Field(description="https://t.me/<bot>?startapp=ri_<base62>: открывает S56")
    start_param: str = Field(description="Код startapp: ri_<base62>")
    client_name: str | None = Field(description="Кому отправлена — заметка специалиста")
    status: str = Field(
        description="waiting — ждём отзыв (можно отозвать), expired — истекла, under_review — на"
        " модерации, published — опубликован, removed — снят"
    )
    reviewer_name: str | None = Field(
        description="Кто оставил отзыв: «Имя Ф.»; ещё никто или аккаунт удалён — null"
    )
    rating: int | None = Field(description="Оценка в оставленном отзыве")
    created_at: datetime = Field(description="«Ссылка отправлена 2 дня назад»")
    expires_at: datetime
    used_at: datetime | None = Field(description="«Отзыв получен вчера»")
    published_at: datetime | None = Field(description="«Оценка 5 · 5 дней назад»")


class ReviewInvitesOut(BaseModel):
    items: list[ReviewInviteOut] = Field(description="Новые первыми; отозванных нет")
    limit: int = Field(default=MAX_INVITES, description="Сколько мест всего: 5")
    taken: int = Field(description="Занято мест: ждут отзыва и использованные — «4 из 5»")


def review_invite_out(
    item: InviteItem, *, url: str, start_param: str, names: Mapping[UserId, str]
) -> ReviewInviteOut:
    listing = item.listing
    name = names.get(listing.used_by) if listing.used_by is not None else None
    return ReviewInviteOut(
        token=listing.token,
        url=url,
        start_param=start_param,
        client_name=listing.client_name,
        status=item.status.value,
        reviewer_name=short_name(name) if name else None,
        rating=listing.rating,
        created_at=listing.created_at,
        expires_at=listing.expires_at,
        used_at=listing.used_at,
        published_at=listing.published_at,
    )


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_REPLY)


class ReplyOut(BaseModel):
    body: str
    at: datetime
    status: str = Field(description="under_review | published | removed")


class ReviewOut(BaseModel):
    """Отзыв автору или тому, о ком он: с ответом в любом статусе."""

    id: UUID
    kind: str = Field(description="deal | pre_platform — «до платформы», в рейтинг не входит")
    deal_id: UUID | None
    rating: int
    criteria: dict[str, int]
    body: str | None
    work_title: str | None = Field(description="«Что делал мастер» — у отзыва до платформы")
    status: str = Field(description="under_review | published | removed")
    created_at: datetime
    published_at: datetime | None
    reply: ReplyOut | None

    @classmethod
    def of(cls, review: Review) -> ReviewOut:
        reply = review.reply
        return cls(
            id=review.id,
            kind=review.kind.value,
            work_title=review.work_title,
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
    kind: str = Field(description="deal | pre_platform — «до платформы», без сделки")
    deal_id: UUID | None
    deal_title: str | None
    work_title: str | None = Field(description="«Что делал мастер» — у отзыва до платформы")
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
        kind=item.kind,
        work_title=item.work_title,
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
