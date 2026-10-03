"""BFF списка блокировок S44 (DEVELOPMENT_PLAN 4.7; ARCHITECTURE §8.5 `GET /me/blocks`): кого я
заблокировал — имя «Олег Р.» и когда (identity), у специалиста — фото и ссылка на карточку
(specialists, media). Заблокировать и разблокировать — `PUT` и `DELETE /me/blocks/{user_id}`
модуля identity. Ответ — без кэша: список меняется действиями самого человека.
"""

from datetime import datetime
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from app.interfaces.http.views.specialist import CardPhotoOut, _photo
from app.modules.identity.api import IdentityApi
from app.modules.media.api import MediaApi
from app.modules.specialists.api import SpecialistsApi
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.principal import Principal
from app.platform.text.names import short_name

PUBLISHED = "published"

router = APIRouter(tags=["views"])


class BlockedUserOut(BaseModel):
    user_id: UUID
    display_name: str = Field(description="Имя и первая буква фамилии: «Олег Р.»")
    avatar: CardPhotoOut | None = Field(description="Фото опубликованного профиля специалиста")
    profile_id: UUID | None = Field(description="Опубликованный профиль: ссылка на S08")
    blocked_at: datetime


class BlocksOut(BaseModel):
    items: list[BlockedUserOut] = Field(description="Недавние первыми")


@router.get("/me/blocks", response_model=BlocksOut, dependencies=AUTHENTICATED)
@inject
async def list_blocks(
    principal: FromDishka[Principal],
    identity: FromDishka[IdentityApi],
    specialists: FromDishka[SpecialistsApi],
    media: FromDishka[MediaApi],
    response: Response,
) -> BlocksOut:
    """Заблокированные S44 (и число на строке S43): недавние первыми."""
    response.headers["Cache-Control"] = "private, no-store"
    blocked = await identity.blocked_users(principal.user_id)
    refs = await specialists.profiles_of([user.user_id for user in blocked]) if blocked else {}
    published = [ref.id for ref in refs.values() if ref.status == PUBLISHED]
    cards = await specialists.public_cards(published) if published else {}
    by_user = {card.user_id: card for card in cards.values()}
    avatars = [card.avatar_media_id for card in cards.values() if card.avatar_media_id]
    photos = await media.refs(avatars) if avatars else {}
    items = []
    for user in blocked:
        card = by_user.get(user.user_id)
        media_id = card.avatar_media_id if card is not None else None
        items.append(
            BlockedUserOut(
                user_id=user.user_id,
                # у специалиста — имя с карточки: его человек и видел на S08 и в чате
                display_name=short_name(card.display_name if card else user.display_name),
                avatar=_photo(photos.get(media_id)) if media_id is not None else None,
                profile_id=card.id if card is not None else None,
                blocked_at=user.blocked_at,
            )
        )
    return BlocksOut(items=items)
