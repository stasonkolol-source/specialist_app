"""BFF откликов на свою заявку S23 (DEVELOPMENT_PLAN 5.6): отклики из jobs, исполнитель — из
specialists (профиль, основной район), media (фото профиля), reviews (рейтинг или «Новый
специалист») и identity (имя подработчика, «Телефон подтверждён»).

Только владельцу: чужая заявка — 404 `job_not_found`. Ответ, в котором есть новые отклики,
отмечает, что клиент их видел: бейдж новых на S22 гаснет, уведомление о них не уходит. S23
опрашивает раз в 15 секунд, поэтому опрос без новых ничего не пишет, а исполнители читаются
пачками — карточка профиля, имена, рейтинги, фото и районы по запросу на всех (было по
нескольку запросов на каждый отклик). Профиль, который скрыли или удалили, показывается без
него — как подработка с именем.
"""

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

from app.interfaces.http.views.specialist import (
    CardNamedOut,
    CardPhotoOut,
    _money,
    _photo,
    _visible_cards,
)
from app.modules.geo.api import GeoApi
from app.modules.identity.api import IdentityApi
from app.modules.jobs.api import JobsApi
from app.modules.media.api import MediaApi
from app.modules.reviews.api import ReviewsApi
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.http.money import MoneyOut
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal

router = APIRouter(tags=["views"])
JobPath = Annotated[UUID, Path(description="id своей заявки")]


ResponsePriceKind = Literal["fixed", "from", "hourly", "negotiable"]
ResponseState = Literal[
    "submitted", "viewed", "shortlisted", "accepted", "declined", "withdrawn", "not_selected"
]


class ResponseCardPriceOut(BaseModel):
    type: ResponsePriceKind
    amount: MoneyOut | None


class ResponsePerformerCardOut(BaseModel):
    display_name: str = Field(description="Аккаунт удалён — пусто")
    profile_id: UUID | None = Field(description="Профиль специалиста; без него — подработка")
    kind: str | None = Field(description="pro | casual; без профиля — null")
    avatar: CardPhotoOut | None
    district: CardNamedOut | None = Field(description="Основной район профиля")
    rating: float | None = Field(description="Когда отзывов достаточно; иначе is_new")
    rating_count: int
    is_new: bool = Field(description="«Новый специалист»: меньше трёх отзывов по сделкам")
    phone_verified: bool


class ResponseCardOut(BaseModel):
    id: UUID
    status: ResponseState
    message: str
    price: ResponseCardPriceOut
    availability_note: str | None
    is_first: bool = Field(description="«Откликнулся первым»")
    is_new: bool = Field(description="Клиент ещё не видел этот отклик")
    created_at: datetime
    revision: int = Field(
        description="Редакция предложения: If-Match при выборе (POST /responses/{id}/accept);"
        " исполнитель успел поправить — 409 offer_changed"
    )
    performer: ResponsePerformerCardOut


class ResponseCardsOut(BaseModel):
    items: list[ResponseCardOut] = Field(description="По времени отклика")


@router.get(
    "/jobs/{job_id:uuid}/response-cards",
    response_model=ResponseCardsOut,
    dependencies=AUTHENTICATED,
)
@inject
async def list_response_cards(
    *,
    job_id: JobPath,
    principal: FromDishka[Principal],
    jobs: FromDishka[JobsApi],
    specialists: FromDishka[SpecialistsApi],
    identity: FromDishka[IdentityApi],
    media: FromDishka[MediaApi],
    reviews: FromDishka[ReviewsApi],
    geo: FromDishka[GeoApi],
    uow: FromDishka[UnitOfWork],
    locale: FromDishka[Locale],
) -> ResponseCardsOut:
    """Отклики на свою заявку для S23: исполнитель с фото, районом и рейтингом, «Откликнулся
    первым», новые для клиента. Ответ отмечает отклики просмотренными. Отклики тех, с кем у
    клиента блокировка (4.7), не показываются: имена и блокировки — одним чтением identity."""
    responses = await jobs.owner_responses(job_id, principal.user_id)
    users = await identity.users(
        {response.performer_id for response in responses}, viewer_id=principal.user_id
    )
    responses = [
        response
        for response in responses
        if (user := users.get(response.performer_id)) is None or user.block is None
    ]
    cards = await _visible_cards(
        {r.profile_id for r in responses if r.profile_id is not None}, specialists, identity
    )
    ratings = await reviews.summaries(list(cards)) if cards else {}
    avatars = await media.refs(
        [card.avatar_media_id for card in cards.values() if card.avatar_media_id is not None]
    )
    areas = await geo.districts(
        {card.primary_area_id for card in cards.values() if card.primary_area_id is not None}
    )
    items = []
    for response in responses:
        card = cards.get(response.profile_id) if response.profile_id else None
        user = users.get(response.performer_id)
        name = user.display_name if user is not None and not user.is_deleted else ""
        rating = ratings.get(card.id) if card is not None else None
        area = areas.get(card.primary_area_id) if card and card.primary_area_id else None
        avatar = avatars.get(card.avatar_media_id) if card and card.avatar_media_id else None
        items.append(
            ResponseCardOut(
                id=response.id,
                status=cast(ResponseState, response.status),
                message=response.message,
                price=ResponseCardPriceOut(
                    type=cast(ResponsePriceKind, response.price_type),
                    amount=_money(response.price_amount),
                ),
                availability_note=response.availability_note,
                is_first=response.is_first,
                is_new=response.is_new,
                created_at=response.created_at,
                revision=response.revision,
                performer=ResponsePerformerCardOut(
                    display_name=card.display_name if card is not None else name,
                    profile_id=card.id if card is not None else None,
                    kind=card.kind if card is not None else None,
                    avatar=_photo(avatar),
                    district=(
                        CardNamedOut(id=area.id, name=area.name.get(locale))
                        if area is not None
                        else None
                    ),
                    rating=None if rating is None or rating.is_new else rating.mean,
                    rating_count=rating.count if rating is not None else 0,
                    is_new=rating is None or rating.is_new,
                    phone_verified=bool(user is not None and user.phone_verified),
                ),
            )
        )
    if any(response.is_new for response in responses):
        # опрос без новых откликов ничего не пишет: отмечать нечего
        async with uow:
            await jobs.see_responses(job_id)
    return ResponseCardsOut(items=items)
