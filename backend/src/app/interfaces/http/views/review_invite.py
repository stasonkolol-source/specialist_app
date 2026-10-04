"""Форма «отзыва до платформы» по приглашению S56 (DEVELOPMENT_PLAN 7.6а; ARCHITECTURE §8.5
`GET /review-invites/{token}` 🔓): кто просит отзыв — имя, фото, «коротко о себе» и категории
специалиста — из фасадов reviews, specialists, identity, media и catalog.

Ссылка отозвана, истекла, по ней уже оставили отзыв, её нет или профиль не виден в каталоге
(скрыт, снят санкцией, удалён) — одинаково 404, без подсказки почему. Открыть может и гость:
форма просит войти только при отправке (`POST /review-invites/{token}`, модуль reviews).
Вошедшему специалисту по своей же ссылке — `is_own`: S56 объяснит, что ссылку надо переслать
клиенту, а не заполнять самому.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel, Field

from app.interfaces.http.views.specialist import (
    CardNamedOut,
    CardPhotoOut,
    _avatar_ids,
    _categories,
    _photo,
    _visible,
)
from app.modules.catalog.api import CatalogApi
from app.modules.identity.api import IdentityApi
from app.modules.media.api import MediaApi
from app.modules.reviews.api import ReviewsApi
from app.modules.specialists.api import SpecialistsApi
from app.platform.http.ratelimit import GuestOrUserRateLimit
from app.platform.http.security import optional_principal
from app.platform.kernel.errors import NotFoundError
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.ratelimit import Rate

INVITE_GUEST = Rate("views.review_invite_guest", "30/minute")
INVITE_USER = Rate("views.review_invite_user", "60/minute")
"""Форму открывают по ссылке раз-другой: десятки в минуту — уже подбор."""

router = APIRouter(tags=["views"])
invite_limit = [Depends(GuestOrUserRateLimit(guest=INVITE_GUEST, user=INVITE_USER))]
Viewer = Annotated[Principal | None, Depends(optional_principal)]
TokenPath = Annotated[UUID, Path(description="Секрет ссылки-приглашения (из ri_<base62>)")]


class InviteSpecialistOut(BaseModel):
    profile_id: UUID
    display_name: str = Field(description="«Алексей Морозов»")
    first_name: str = Field(description="«Алексей просит оставить отзыв…», «Подтверждаю: Алексей…»")
    avatar: CardPhotoOut | None
    headline: str | None = Field(description="«Электрик · мелкий ремонт · люстры»")
    categories: list[CardNamedOut]


class ReviewInviteFormOut(BaseModel):
    specialist: InviteSpecialistOut
    expires_at: datetime = Field(description="До когда ссылка действует")
    is_own: bool = Field(description="Ссылку открыл сам специалист: отзыв о себе не оставить")


@router.get(
    "/review-invites/{token:uuid}", response_model=ReviewInviteFormOut, dependencies=invite_limit
)
@inject
async def get_review_invite(
    token: TokenPath,
    viewer: Viewer,
    response: Response,
    reviews: FromDishka[ReviewsApi],
    specialists: FromDishka[SpecialistsApi],
    identity: FromDishka[IdentityApi],
    media: FromDishka[MediaApi],
    catalog: FromDishka[CatalogApi],
    locale: FromDishka[Locale],
) -> ReviewInviteFormOut:
    """Форма S56: специалист, который просит отзыв о прошлой работе."""
    response.headers["Cache-Control"] = "private, no-store"
    invite = await reviews.open_invite(token)
    if invite is None:
        raise NotFoundError()
    profile = await _visible(invite.profile_id, specialists, identity)
    avatars = await media.refs(_avatar_ids(profile))
    name = profile.display_name
    return ReviewInviteFormOut(
        specialist=InviteSpecialistOut(
            profile_id=profile.id,
            display_name=name,
            first_name=name.split()[0] if name.split() else name,
            avatar=_photo(avatars.get(profile.avatar_media_id))
            if profile.avatar_media_id
            else None,
            headline=profile.headline,
            categories=await _categories(catalog, list(profile.category_ids), locale),
        ),
        expires_at=invite.expires_at,
        is_own=viewer is not None and viewer.user_id == profile.user_id,
    )
