"""BFF откликов на свою заявку S23 (DEVELOPMENT_PLAN 5.6): отклики из jobs, исполнитель — из
specialists (профиль, основной район), media (фото профиля), reviews (рейтинг или «Новый
специалист») и identity (имя подработчика, «Телефон подтверждён»).

Только владельцу: чужая заявка — 404 `job_not_found`. Каждый ответ отмечает, что клиент видел
отклики: бейдж новых на S22 гаснет, уведомление о них не уходит. S23 опрашивает раз в 15 секунд.
Профиль, который скрыли или удалили, показывается без него — как подработка с именем.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

from app.interfaces.http.views.specialist import CardNamedOut, CardPhotoOut, _money, _photo
from app.modules.geo.api import GeoApi
from app.modules.identity.api import IdentityApi
from app.modules.jobs.api import JobsApi, OwnerResponseView
from app.modules.media.api import MediaApi, MediaRef
from app.modules.reviews.api import ReviewsApi
from app.modules.specialists.api import PublicProfile, SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.http.money import MoneyOut
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.ids import MediaId, UserId
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
    первым», новые для клиента. Ответ отмечает отклики просмотренными."""
    responses = await jobs.owner_responses(job_id, principal.user_id)
    profiles = await _profiles(specialists, identity, responses)
    ratings = await reviews.summaries(list(profiles))
    avatars = await media.refs(
        [p.avatar_media_id for p in profiles.values() if p.avatar_media_id is not None]
    )
    cards = []
    for response in responses:
        profile = profiles.get(response.profile_id) if response.profile_id else None
        user = await identity.get_user(response.performer_id)
        name = user.display_name if user is not None and not user.is_deleted else ""
        rating = ratings.get(profile.id) if profile is not None else None
        district = None
        if profile is not None and profile.area_ids:
            found = await geo.district(profile.area_ids[0])
            if found is not None:
                district = CardNamedOut(id=found.id, name=found.name.get(locale))
        cards.append(
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
                performer=ResponsePerformerCardOut(
                    display_name=profile.display_name if profile is not None else name,
                    profile_id=profile.id if profile is not None else None,
                    kind=profile.kind if profile is not None else None,
                    avatar=_avatar(avatars, profile),
                    district=district,
                    rating=None if rating is None or rating.is_new else round(rating.average, 1),
                    rating_count=rating.count if rating is not None else 0,
                    is_new=rating is None or rating.is_new,
                    phone_verified=bool(user is not None and user.phone_verified),
                ),
            )
        )
    async with uow:
        await jobs.see_responses(job_id)
    return ResponseCardsOut(items=cards)


async def _profiles(
    specialists: SpecialistsApi, identity: IdentityApi, responses: list[OwnerResponseView]
) -> dict[UUID, PublicProfile]:
    """Опубликованные профили откликнувшихся, чьи авторы не скрыты санкцией."""
    found: dict[UUID, PublicProfile] = {}
    for response in responses:
        if response.profile_id is None or response.profile_id in found:
            continue
        profile = await specialists.public_profile(response.profile_id)
        if profile is not None:
            found[profile.id] = profile
    hidden = await identity.hidden_from_search(
        [UserId(profile.user_id) for profile in found.values()]
    )
    return {pid: profile for pid, profile in found.items() if profile.user_id not in hidden}


def _avatar(
    avatars: Mapping[MediaId, MediaRef], profile: PublicProfile | None
) -> CardPhotoOut | None:
    if profile is None or profile.avatar_media_id is None:
        return None
    return _photo(avatars.get(profile.avatar_media_id))
