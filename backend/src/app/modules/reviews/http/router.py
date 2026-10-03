"""HTTP reviews (DEVELOPMENT_PLAN 7.2; ARCHITECTURE §7.9, §8.5): отзывы по сделкам.

- `POST /deals/{id}/review` — отзыв клиента по завершённой сделке (S27): оценка, критерии,
  текст; не позже 14 дней после завершения, один раз (409 `review_not_allowed`,
  `review_exists`). Отзыв виден на карточке специалиста после автопроверки;
- `POST /reviews/{id}/reply` — один публичный ответ того, о ком отзыв (409 `reply_exists`);
  виден после проверки;
- `GET /me/reviews?direction=received|written` — «Мои отзывы» (S28).

Отзывы на карточке специалиста (S08, S11) отдаёт BFF `interfaces/http/views/specialist.py`.
"""

from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Path, Query, status

from app.modules.reviews.application.dto import ReviewsDirection
from app.modules.reviews.application.use_cases.leave_review import (
    LeaveReview,
    LeaveReviewCommand,
)
from app.modules.reviews.application.use_cases.list_my_reviews import (
    ListMyReviews,
    ListMyReviewsCommand,
)
from app.modules.reviews.application.use_cases.reply_to_review import (
    ReplyToReview,
    ReplyToReviewCommand,
)
from app.modules.reviews.http.schemas import (
    MyReviewsPageOut,
    ReplyIn,
    ReviewIn,
    ReviewOut,
    my_review_out,
)
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import DealId
from app.platform.kernel.pagination import DEFAULT_LIMIT, MAX_LIMIT, PageRequest
from app.platform.kernel.principal import Principal

router = APIRouter(tags=["reviews"])

DealPath = Annotated[UUID, Path(description="Сделка")]
ReviewPath = Annotated[UUID, Path(description="Отзыв")]


@router.post(
    "/deals/{deal_id:uuid}/review",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=AUTHENTICATED,
)
@inject
async def leave_review(
    deal_id: DealPath,
    body: ReviewIn,
    principal: FromDishka[Principal],
    leave: FromDishka[LeaveReview],
) -> ReviewOut:
    """Отзыв по завершённой сделке: ждёт автопроверки и публикуется после неё."""
    review = await leave(
        LeaveReviewCommand(
            actor_id=principal.user_id,
            deal_id=DealId(deal_id),
            rating=body.rating,
            criteria={criterion.value: value for criterion, value in body.criteria.items()},
            body=body.body,
        )
    )
    return ReviewOut.of(review)


@router.post(
    "/reviews/{review_id:uuid}/reply",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=AUTHENTICATED,
)
@inject
async def reply_to_review(
    review_id: ReviewPath,
    body: ReplyIn,
    principal: FromDishka[Principal],
    reply: FromDishka[ReplyToReview],
) -> ReviewOut:
    """Ответ на отзыв о себе: один, виден после проверки."""
    review = await reply(
        ReplyToReviewCommand(actor_id=principal.user_id, review_id=review_id, body=body.body)
    )
    return ReviewOut.of(review)


@router.get("/me/reviews", response_model=MyReviewsPageOut, dependencies=AUTHENTICATED)
@inject
async def list_my_reviews(
    *,
    direction: Annotated[
        ReviewsDirection, Query(description="received — обо мне, written — мои")
    ] = ReviewsDirection.RECEIVED,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    principal: FromDishka[Principal],
    reviews: FromDishka[ListMyReviews],
) -> MyReviewsPageOut:
    """«Мои отзывы» (S28): полученные (опубликованные, с моим ответом) или написанные."""
    found = await reviews(
        ListMyReviewsCommand(
            actor_id=principal.user_id,
            direction=direction,
            page=PageRequest(limit=limit, cursor=cursor),
        )
    )
    received = direction is ReviewsDirection.RECEIVED
    return MyReviewsPageOut(
        items=[
            my_review_out(item, received=received, names=found.names, titles=found.titles)
            for item in found.page.items
        ],
        next_cursor=found.page.next_cursor,
    )
