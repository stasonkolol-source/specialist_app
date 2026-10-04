"""HTTP reviews (DEVELOPMENT_PLAN 7.2; ARCHITECTURE §7.9, §8.5): отзывы по сделкам.

- `POST /deals/{id}/review` — отзыв клиента по завершённой сделке (S27): оценка, критерии,
  текст; не позже 14 дней после завершения, один раз (409 `review_not_allowed`,
  `review_exists`). Отзыв виден на карточке специалиста после автопроверки;
- `POST /reviews/{id}/reply` — один публичный ответ того, о ком отзыв (409 `reply_exists`);
  виден после проверки;
- `GET /me/reviews?direction=received|written` — «Мои отзывы» (S28);
- `POST /me/profile/review-invites`, `GET /me/profile/review-invites`,
  `DELETE /me/profile/review-invites/{token}` — ссылки прошлым клиентам на «отзыв до платформы»
  (S55, 7.6а): не больше пяти занятых мест (409 `review_invites_full`), только у опубликованного
  профиля (409 `review_invites_unavailable`), отозвать — неиспользованную (409
  `review_invite_used`);
- `POST /review-invites/{token}` — отзыв по приглашению (S56): вход обязателен; ссылка
  недействительна — 404 `review_invite_not_found`, о себе — 409 `own_profile_review`.

Отзывы на карточке специалиста (S08, S11) отдаёт BFF `interfaces/http/views/specialist.py`, форму
S56 по ссылке — `interfaces/http/views/review_invite.py`.
"""

from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Path, Query, status

from app.modules.reviews.application.dto import InviteListing, ReviewsDirection
from app.modules.reviews.application.use_cases.create_review_invite import (
    CreateReviewInvite,
    CreateReviewInviteCommand,
)
from app.modules.reviews.application.use_cases.leave_invite_review import (
    LeaveInviteReview,
    LeaveInviteReviewCommand,
)
from app.modules.reviews.application.use_cases.leave_review import (
    LeaveReview,
    LeaveReviewCommand,
)
from app.modules.reviews.application.use_cases.list_my_reviews import (
    ListMyReviews,
    ListMyReviewsCommand,
)
from app.modules.reviews.application.use_cases.list_review_invites import (
    InviteItem,
    ListReviewInvites,
    ListReviewInvitesCommand,
)
from app.modules.reviews.application.use_cases.reply_to_review import (
    ReplyToReview,
    ReplyToReviewCommand,
)
from app.modules.reviews.application.use_cases.revoke_review_invite import (
    RevokeReviewInvite,
    RevokeReviewInviteCommand,
)
from app.modules.reviews.domain.invite import InviteStatus
from app.modules.reviews.http.schemas import (
    InviteReviewIn,
    MyReviewsPageOut,
    ReplyIn,
    ReviewIn,
    ReviewInviteIn,
    ReviewInviteOut,
    ReviewInvitesOut,
    ReviewOut,
    my_review_out,
    review_invite_out,
)
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import DealId, UserId
from app.platform.kernel.pagination import DEFAULT_LIMIT, MAX_LIMIT, PageRequest
from app.platform.kernel.principal import Principal
from app.platform.settings import TelegramSettings
from app.platform.telegram.deeplinks import LinkType, StartLink, encode_start_param, startapp_url

router = APIRouter(tags=["reviews"])

DealPath = Annotated[UUID, Path(description="Сделка")]
ReviewPath = Annotated[UUID, Path(description="Отзыв")]
TokenPath = Annotated[UUID, Path(description="Секрет ссылки-приглашения")]


def _invite_out(item: InviteItem, bot: str, names: dict[UserId, str]) -> ReviewInviteOut:
    """Строка S55 со ссылкой `t.me/<bot>?startapp=ri_<base62>`."""
    code = encode_start_param(StartLink(type=LinkType.REVIEW_INVITE, id=item.listing.token))
    return review_invite_out(item, url=startapp_url(bot, code), start_param=code, names=names)


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


@router.post(
    "/me/profile/review-invites",
    response_model=ReviewInviteOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=AUTHENTICATED,
)
@inject
async def create_review_invite(
    body: ReviewInviteIn,
    principal: FromDishka[Principal],
    create: FromDishka[CreateReviewInvite],
    telegram: FromDishka[TelegramSettings],
) -> ReviewInviteOut:
    """Ссылка-приглашение прошлому клиенту на «отзыв до платформы» (S55): одна ссылка — один
    клиент, 30 дней, не больше пяти занятых мест."""
    invite = await create(
        CreateReviewInviteCommand(actor_id=principal.user_id, client_name=body.client_name)
    )
    item = InviteItem(
        listing=InviteListing(
            token=invite.token,
            client_name=invite.client_name,
            created_at=invite.created_at,
            expires_at=invite.expires_at,
            used_by=None,
            used_at=None,
            review_id=None,
            review_status=None,
            rating=None,
            published_at=None,
        ),
        status=InviteStatus.WAITING,
    )
    return _invite_out(item, telegram.bot_username, {})


@router.get(
    "/me/profile/review-invites", response_model=ReviewInvitesOut, dependencies=AUTHENTICATED
)
@inject
async def list_review_invites(
    principal: FromDishka[Principal],
    invites: FromDishka[ListReviewInvites],
    telegram: FromDishka[TelegramSettings],
) -> ReviewInvitesOut:
    """Приглашения S55: статус каждого, кто оставил отзыв, сколько мест из пяти занято."""
    found = await invites(ListReviewInvitesCommand(actor_id=principal.user_id))
    return ReviewInvitesOut(
        items=[_invite_out(item, telegram.bot_username, found.names) for item in found.items],
        taken=found.taken,
    )


@router.delete(
    "/me/profile/review-invites/{token:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=AUTHENTICATED,
)
@inject
async def revoke_review_invite(
    token: TokenPath,
    principal: FromDishka[Principal],
    revoke: FromDishka[RevokeReviewInvite],
) -> None:
    """Отозвать свою неиспользованную ссылку: она перестаёт открываться, место освобождается."""
    await revoke(RevokeReviewInviteCommand(actor_id=principal.user_id, token=token))


@router.post(
    "/review-invites/{token:uuid}",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=AUTHENTICATED,
)
@inject
async def leave_invite_review(
    token: TokenPath,
    body: InviteReviewIn,
    principal: FromDishka[Principal],
    leave: FromDishka[LeaveInviteReview],
) -> ReviewOut:
    """«Отзыв до платформы» по приглашению (S56): ждёт модератора, на карточке — с отдельной
    меткой, в рейтинг не входит."""
    review = await leave(
        LeaveInviteReviewCommand(
            actor_id=principal.user_id,
            token=token,
            rating=body.rating,
            work_title=body.work_title,
            body=body.body,
        )
    )
    return ReviewOut.of(review)
