"""«Поделиться» (DEVELOPMENT_PLAN 7.4; ARCHITECTURE §8.5 `POST /share`, §11.4): ссылка
`t.me/<bot>?startapp=<код>` и карточка для `WebApp.shareMessage` — S08, S10, S15, S21, S23.

BFF решает, можно ли делиться и что показать: только публичным — опубликованным профилем
специалиста, чей автор не скрыт санкцией (как на S08), и заявкой, которую видит гость
(опубликована, не прямой запрос, не удалена). Иначе 404, как у самих экранов. В карточке — то,
что и так видно на S08 и S15: у специалиста имя, «коротко о себе», рейтинг или «Новый
специалист», «Телефон подтверждён», район и цена «от»; у заявки — название, бюджет и время (теми
же словами, что карточка B1, platform/i18n/jobs.py) и место. Ни адреса, ни точки, ни контактов.
Счётчика откликов нет: отправленная карточка не обновляется, и число устарело бы. Подпись к
ссылке (`text`) — первые две строки карточки простым текстом. Ссылку, код приглашения `_r` и
карточку собирает growth. Карточки нет (гость, Bot API не принял) — клиент делится ссылкой:
`t.me/share/url` или копирование.
"""

import html
import re
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

import babel
from babel.numbers import format_decimal
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.interfaces.http.views.specialist import _visible
from app.modules.geo.api import GeoApi
from app.modules.growth.api import GrowthApi, ShareRequest, ShareTarget, ShareText
from app.modules.identity.api import IdentityApi
from app.modules.jobs.api import JobsApi, PublicJob
from app.modules.pricing.api import PricingApi
from app.modules.reviews.api import RatingSummary, ReviewsApi
from app.modules.specialists.api import PublicProfile, SpecialistsApi
from app.platform.http.ratelimit import GuestOrUserRateLimit
from app.platform.http.security import optional_principal
from app.platform.i18n.catalogs import CATALOG_NAMES
from app.platform.i18n.jobs import budget, price, when
from app.platform.i18n.translator import Translator
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import NotFoundError
from app.platform.kernel.ids import CityId, DistrictId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal
from app.platform.ratelimit import Rate
from app.platform.telegram.texts import html_text, plain_text

SHARE_GUEST = Rate("views.share_guest", "10/minute")
SHARE_USER = Rate("views.share_user", "30/minute")
"""Ссылку берут по нажатию «Поделиться»: десятки в минуту — уже не человек."""
CAPTION_LINES: Final = 2
"""Подпись к ссылке — заголовок и строка под ним: имя и «коротко о себе», название и бюджет."""
TAG = re.compile(r"<[^>]+>")

router = APIRouter(tags=["growth"])
share_limit = [Depends(GuestOrUserRateLimit(guest=SHARE_GUEST, user=SHARE_USER))]
Viewer = Annotated[Principal | None, Depends(optional_principal)]


class ShareIn(BaseModel):
    entity_type: ShareTarget = Field(description="specialist — профиль S08, job — заявка S15")
    entity_id: UUID = Field(description="id профиля специалиста или заявки")


class ShareOut(BaseModel):
    url: str = Field(description="https://t.me/<bot>?startapp=<код>: открывает S08 или S15")
    start_param: str = Field(description="Код startapp: s_… или j_…, у вошедшего — с _r<код>")
    text: str = Field(
        description="Подпись для t.me/share/url и копирования: первые две строки карточки —"
        " имя и «коротко о себе» или название и бюджет"
    )
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


async def _primary_area(geo: GeoApi, profile: PublicProfile) -> DistrictId | None:
    """Основной район профиля; у выезжающего во все кварталы — нет: карточка называет город, а не
    первый по алфавиту квартал (QA SMOKE-6)."""
    if not profile.area_ids or await geo.covers_city(profile.city_id, profile.area_ids):
        return None
    return profile.area_ids[0]


def specialist_card(
    translator: Translator,
    locale: Locale,
    *,
    name: str,
    headline: str | None,
    rating: RatingSummary | None,
    phone_verified: bool,
    place: str | None,
    price_from: int | None,
) -> tuple[ShareText, str]:
    """Карточка профиля (как S08: рейтинг или «Новый специалист», подтверждённый телефон, район и
    цена «от») и подпись к ссылке."""
    heading = html_text(translator, "share.specialist.text", locale, name=_flat(name))
    verified = plain_text(translator, "share.specialist.phone_verified", locale)
    lines = [
        headline,
        _rating(translator, locale, rating),
        verified if phone_verified else None,
        _joined(place, price(translator, locale, "from", price_from)),
    ]
    card = ShareText(
        title=name,
        description=headline,
        text=heading + _lines(lines),
        button_text=plain_text(translator, "share.specialist.button", locale),
    )
    return card, _caption(heading, lines)


def job_card(
    translator: Translator, locale: Locale, job: PublicJob, place: str | None, now: datetime
) -> tuple[ShareText, str]:
    """Карточка заявки: бюджет и время — как в карточке B1, «сегодня» — от момента, когда
    делятся; место — район и город."""
    heading = html_text(translator, "share.job.text", locale, title=_flat(job.title))
    terms = _joined(
        budget(
            translator,
            locale,
            kind=job.budget_type,
            low=job.budget_min,
            high=job.budget_max,
            unit=job.budget_unit,
        ),
        when(
            translator,
            locale,
            start=job.preferred_from,
            end=job.preferred_to,
            urgency=job.urgency,
            now=now,
        ),
    )
    lines = [terms, place]
    card = ShareText(
        title=job.title,
        description=place,
        text=heading + _lines(lines),
        button_text=plain_text(translator, "share.job.button", locale),
    )
    return card, _caption(heading, lines)


def _rating(translator: Translator, locale: Locale, summary: RatingSummary | None) -> str:
    """«★ 4,9 — 37 отзывов», как на S08; пока отзывов мало — «Новый специалист»."""
    if summary is None or summary.is_new:
        return plain_text(translator, "share.specialist.new", locale)
    cldr = babel.Locale.parse(CATALOG_NAMES[locale])
    # у целых чисел `other` бывает только там, где нет `many` (сербский): это та же форма
    form = cldr.plural_form(summary.count)
    return plain_text(
        translator,
        f"share.specialist.rating.{'many' if form == 'other' else form}",
        locale,
        rating=format_decimal(summary.mean, format="0.0", locale=cldr),
        count=format_decimal(summary.count, locale=cldr),
    )


def _joined(*parts: str | None) -> str | None:
    return " · ".join(part for part in parts if part) or None


def _flat(value: str | None) -> str | None:
    """Строка карточки — одной строкой: перенос в «коротко о себе» не сдвигает подпись.
    Неразрывные пробелы («5 000 RSD») остаются как есть."""
    parts = (part.strip() for part in (value or "").splitlines())
    return " ".join(part for part in parts if part) or None


def _lines(values: list[str | None]) -> str:
    """Строки под заголовком карточки: данные людей — текстом, не разметкой."""
    return "".join(f"\n{html.escape(line, quote=False)}" for line in map(_flat, values) if line)


def _caption(heading: str, values: list[str | None]) -> str:
    """Первые строки карточки простым текстом: заголовок без разметки (имя в нём уже
    экранировано — вернётся как было) и что есть под ним."""
    lines = [html.unescape(TAG.sub("", heading)), *filter(None, map(_flat, values))]
    return "\n".join(lines[:CAPTION_LINES])


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
    reviews: FromDishka[ReviewsApi],
    pricing: FromDishka[PricingApi],
    geo: FromDishka[GeoApi],
    translator: FromDishka[Translator],
    clock: FromDishka[Clock],
    locale: FromDishka[Locale],
) -> ShareOut:
    """Ссылка «Поделиться» на профиль специалиста или заявку и карточка для shareMessage."""
    response.headers["Cache-Control"] = "private, no-store"
    if body.entity_type is ShareTarget.SPECIALIST:
        profile = await _visible(body.entity_id, specialists, identity)
        user = await identity.get_user(profile.user_id)
        prices = (await pricing.search_prices([profile.id])).get(profile.id)
        card, text = specialist_card(
            translator,
            locale,
            name=profile.display_name,
            headline=profile.headline,
            rating=(await reviews.summaries([profile.id])).get(profile.id),
            phone_verified=user is not None and user.phone_verified,
            place=await _place(geo, profile.city_id, await _primary_area(geo, profile), locale),
            price_from=prices.price_from if prices is not None else None,
        )
    else:
        job = await jobs.public_job(body.entity_id)
        if job is None or await identity.hidden_from_search([job.client_id]):
            raise NotFoundError()
        place = await _place(geo, job.city_id, job.district_id, locale)
        card, text = job_card(translator, locale, job, place, clock.now())
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
        text=text,
        prepared_message_id=shared.prepared_message_id,
    )
