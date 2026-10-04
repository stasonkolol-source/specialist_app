"""«Поделиться» (DEVELOPMENT_PLAN 7.4; ARCHITECTURE §8.5 `POST /share`, §11.4): ссылка
`t.me/<bot>?startapp=<код>` и карточка для `WebApp.shareMessage` — S08, S10, S15, S21, S23.

BFF решает, можно ли делиться и что показать: только публичным — опубликованным профилем
специалиста, чей автор не скрыт санкцией (как на S08), и заявкой, которую видит гость
(опубликована, не прямой запрос, не удалена). Иначе 404, как у самих экранов. В карточке —
имя и «коротко о себе» специалиста или название заявки и место: ни адреса, ни точки, ни
контактов. Ссылку, код приглашения `_r` и карточку собирает growth. Карточки нет (гость, Bot API
не принял) — клиент делится ссылкой: `t.me/share/url` или копирование.
"""

import html
from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.interfaces.http.views.specialist import _visible
from app.modules.geo.api import GeoApi
from app.modules.growth.api import GrowthApi, ShareRequest, ShareTarget, ShareText
from app.modules.identity.api import IdentityApi
from app.modules.jobs.api import JobsApi
from app.modules.specialists.api import SpecialistsApi
from app.platform.http.ratelimit import GuestOrUserRateLimit
from app.platform.http.security import optional_principal
from app.platform.i18n.translator import Translator
from app.platform.kernel.errors import NotFoundError
from app.platform.kernel.ids import CityId, DistrictId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.ratelimit import Rate
from app.platform.telegram.texts import html_text, plain_text

SHARE_GUEST = Rate("views.share_guest", "10/minute")
SHARE_USER = Rate("views.share_user", "30/minute")
"""Ссылку берут по нажатию «Поделиться»: десятки в минуту — уже не человек."""

router = APIRouter(tags=["growth"])
share_limit = [Depends(GuestOrUserRateLimit(guest=SHARE_GUEST, user=SHARE_USER))]
Viewer = Annotated[Principal | None, Depends(optional_principal)]


class ShareIn(BaseModel):
    entity_type: ShareTarget = Field(description="specialist — профиль S08, job — заявка S15")
    entity_id: UUID = Field(description="id профиля специалиста или заявки")


class ShareOut(BaseModel):
    url: str = Field(description="https://t.me/<bot>?startapp=<код>: открывает S08 или S15")
    start_param: str = Field(description="Код startapp: s_… или j_…, у вошедшего — с _r<код>")
    text: str = Field(description="Подпись для t.me/share/url и копирования: имя или название")
    prepared_message_id: str | None = Field(
        description="Карточка для WebApp.shareMessage; null — делиться ссылкой"
    )


async def _place(
    geo: GeoApi, city_id: CityId, district_id: DistrictId | None, locale: Locale
) -> str | None:
    """«Лиман, Нови-Сад»: район и город на языке того, кто делится."""
    city = await geo.city(city_id)
    found = await geo.districts([district_id]) if district_id is not None else {}
    district = found.get(district_id) if district_id is not None else None
    parts = [
        district.name.get(locale) if district is not None else None,
        city.name.get(locale) if city is not None else None,
    ]
    return ", ".join(part for part in parts if part) or None


def _lines(*values: str | None) -> str:
    """Строки под заголовком карточки: данные людей — текстом, не разметкой."""
    return "".join(f"\n{html.escape(value, quote=False)}" for value in values if value)


@router.post("/share", response_model=ShareOut, dependencies=share_limit)
@inject
async def create_share(
    body: ShareIn,
    viewer: Viewer,
    response: Response,
    growth: FromDishka[GrowthApi],
    specialists: FromDishka[SpecialistsApi],
    identity: FromDishka[IdentityApi],
    jobs: FromDishka[JobsApi],
    geo: FromDishka[GeoApi],
    translator: FromDishka[Translator],
    locale: FromDishka[Locale],
) -> ShareOut:
    """Ссылка «Поделиться» на профиль специалиста или заявку и карточка для shareMessage."""
    response.headers["Cache-Control"] = "private, no-store"
    if body.entity_type is ShareTarget.SPECIALIST:
        profile = await _visible(body.entity_id, specialists, identity)
        name = profile.display_name
        place = await _place(
            geo, profile.city_id, profile.area_ids[0] if profile.area_ids else None, locale
        )
        details = _lines(profile.headline, place)
        card = ShareText(
            title=name,
            description=profile.headline,
            text=html_text(translator, "share.specialist.text", locale, name=name) + details,
            button_text=plain_text(translator, "share.specialist.button", locale),
        )
    else:
        job = await jobs.public_job(body.entity_id)
        if job is None or await identity.hidden_from_search([job.client_id]):
            raise NotFoundError()
        name = job.title
        place = await _place(geo, job.city_id, job.district_id, locale)
        details = _lines(place)
        card = ShareText(
            title=name,
            description=place,
            text=html_text(translator, "share.job.text", locale, title=name) + details,
            button_text=plain_text(translator, "share.job.button", locale),
        )
    shared = await growth.share(
        ShareRequest(
            sharer_id=viewer.user_id if viewer is not None else None,
            target=body.entity_type,
            target_id=body.entity_id,
            card=card,
        )
    )
    return ShareOut(
        url=shared.url,
        start_param=shared.start_param,
        text=name,
        prepared_message_id=shared.prepared_message_id,
    )
