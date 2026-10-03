"""BFF карточки специалиста S08–S11 (DEVELOPMENT_PLAN 4.5, 4.6): профиль, прайс, портфолио и
отзывы — из фасадов specialists, pricing, media, reviews, catalog, geo, identity и search
(ARCHITECTURE §5.2 п. 7).

Профиль виден, если он опубликован, а автор не удалён и не скрыт санкцией — как в поиске;
иначе 404, без подсказки почему. Ответ на языке Accept-Language, с ETag: повторный запрос без
изменений — 304. Фото — готовые варианты; пока файл обрабатывается, его на карточке нет.
Рейтинг — агрегаты reviews (байесовское среднее), отзывы — опубликованные по сделкам с ответом
специалиста, автор — «Имя Ф.» (7.2). «Обычно отвечает за …» — медиана первого ответа
в диалогах за 30 дней из read-model поиска (6.3b; при пяти и больше диалогах с ответом). Бейджи —
v1: пока пусто.
"""

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import BaseModel, Field

from app.modules.catalog.api import CatalogApi
from app.modules.geo.api import GeoApi
from app.modules.identity.api import IdentityApi
from app.modules.media.api import MediaApi, MediaRef
from app.modules.pricing.api import PricingApi, PublicService
from app.modules.reviews.api import PublicReview, RatingSummary, ReviewsApi
from app.modules.search.api import SearchApi
from app.modules.specialists.api import PublicCard, PublicProfile, PublicWork, SpecialistsApi
from app.platform.http.caching import NOT_MODIFIED, cached_json
from app.platform.http.money import MoneyOut
from app.platform.http.ratelimit import GuestOrUserRateLimit
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import NotFoundError
from app.platform.kernel.ids import CategoryId, DistrictId, MediaId
from app.platform.kernel.localized import Locale
from app.platform.kernel.money import Currency, Money
from app.platform.kernel.pagination import DEFAULT_LIMIT, MAX_LIMIT, PageRequest
from app.platform.ratelimit import Rate
from app.platform.text.names import short_name

PROFILE_GUEST = Rate("views.specialist_guest", "60/minute")
PROFILE_USER = Rate("views.specialist_user", "120/minute")
"""Карточка — часть каталога: те же 60 / 120 в минуту (ARCHITECTURE §13.3), свои счётчики."""
MAX_AGE_SECONDS = 60
TOP_SERVICES = 3
PREVIEW_WORKS = 3
"""«Цены» и «Работы» на S08 — по одному ряду, как на артборде; остальное — S09 и S10."""
READY = "ready"
STARS = 5
LATEST_REVIEWS = 1
"""Последний отзыв на S08; остальные — S11."""

router = APIRouter(tags=["views"])
profile_limit = [Depends(GuestOrUserRateLimit(guest=PROFILE_GUEST, user=PROFILE_USER))]
ProfileId = Annotated[UUID, Path(description="id профиля специалиста")]


class CardVariantOut(BaseModel):
    name: str = Field(description="thumb 320 · md 800 · lg 1600")
    url: str
    width: int
    height: int


class CardPhotoOut(BaseModel):
    placeholder: str | None = Field(description="ThumbHash (base64) для мгновенного превью")
    variants: list[CardVariantOut]
    video_url: str | None = None
    duration_ms: int | None = None


class CardNamedOut(BaseModel):
    id: int
    name: str


class CardServiceOut(BaseModel):
    id: UUID
    title: str
    description: str | None
    category_id: int | None
    price_type: str = Field(description="fixed | from | range | hourly | per_unit | negotiable")
    price_min: MoneyOut | None
    price_max: MoneyOut | None
    unit: str | None
    duration_min: int | None


class CardWorkOut(BaseModel):
    id: UUID
    kind: str = Field(description="image | video")
    caption: str | None
    photo: CardPhotoOut


class CardReplyOut(BaseModel):
    body: str
    at: datetime


class CardReviewOut(BaseModel):
    id: UUID
    kind: str = Field(description="deal | pre_platform")
    author_name: str = Field(description="Имя и первая буква фамилии: «Ирина С.»; удалён — пусто")
    rating: int
    criteria: dict[str, int] = Field(description="Оценённые критерии: quality, punctuality, …")
    body: str | None
    category: CardNamedOut | None = Field(description="Услуга сделки")
    published_at: datetime
    reply: CardReplyOut | None = Field(description="Ответ специалиста (прошёл проверку)")


class SpecialistProfileOut(BaseModel):
    id: UUID
    kind: str = Field(description="pro | casual")
    display_name: str
    headline: str | None
    about: str | None
    avatar: CardPhotoOut | None
    city: CardNamedOut | None
    district: CardNamedOut | None = Field(description="Основной район")
    areas: list[CardNamedOut] = Field(description="Районы выезда по порядку")
    travel_radius_km: int | None
    work_modes: list[str]
    languages: list[str]
    categories: list[CardNamedOut]
    available_until: datetime | None = Field(description="«Доступен сегодня до …», если ещё да")
    is_founding: bool
    rating: float | None = Field(description="Когда отзывов достаточно (7.2); иначе is_new")
    rating_count: int
    is_new: bool
    badges: list[str]
    response_time_minutes: int | None = Field(
        description="«Обычно отвечает за …»: медиана первого ответа в диалогах за 30 дней, в"
        " минутах; меньше пяти диалогов с ответом — null"
    )
    services: list[CardServiceOut] = Field(description="Первые позиции прайса (S08)")
    services_count: int
    works: list[CardWorkOut] = Field(description="Превью портфолио (S08)")
    works_count: int
    reviews: list[CardReviewOut] = Field(description="Последний отзыв (S08) — с 7.2")
    published_at: datetime | None


class CardServicesOut(BaseModel):
    items: list[CardServiceOut]
    categories: list[CardNamedOut] = Field(description="Группы прайса S09 в порядке позиций")


class CardWorksOut(BaseModel):
    items: list[CardWorkOut]


class CardRatingOut(BaseModel):
    rating: float | None = Field(description="«4,9», когда отзывов достаточно; иначе is_new")
    count: int = Field(description="Отзывов по сделкам: «до платформы» в рейтинг не входят")
    is_new: bool
    distribution: list[int] = Field(description="Оценок в 1, 2, 3, 4, 5 звёзд — гистограмма S11")
    criteria: dict[str, float] = Field(description="quality, punctuality, communication, price")


class CardReviewsOut(BaseModel):
    summary: CardRatingOut
    items: list[CardReviewOut] = Field(
        description="Опубликованные отзывы по сделкам, новые первыми"
    )
    next_cursor: str | None


async def _visible(
    profile_id: UUID, specialists: SpecialistsApi, identity: IdentityApi
) -> PublicProfile:
    """Опубликованный профиль автора, которого не скрывает санкция; иначе 404 (как в поиске)."""
    profile = await specialists.public_profile(profile_id)
    if profile is None or await identity.hidden_from_search([profile.user_id]):
        raise NotFoundError()
    return profile


async def _visible_card(
    profile_id: UUID, specialists: SpecialistsApi, identity: IdentityApi
) -> PublicCard:
    """Видимость профиля для S09 и S11: та же проверка, что `_visible`, но без описаний,
    категорий и портфолио — экранам они не нужны."""
    card = (await _visible_cards([profile_id], specialists, identity)).get(profile_id)
    if card is None:
        raise NotFoundError()
    return card


async def _visible_cards(
    profile_ids: Collection[UUID], specialists: SpecialistsApi, identity: IdentityApi
) -> dict[UUID, PublicCard]:
    """Опубликованные профили карточками, чьи авторы не удалены и не скрыты санкцией (как в
    поиске), — двумя запросами на пачку (S23, S26, S09, S11)."""
    cards = await specialists.public_cards(profile_ids)
    hidden = await identity.hidden_from_search([card.user_id for card in cards.values()])
    return {pid: card for pid, card in cards.items() if card.user_id not in hidden}


def _photo(ref: MediaRef | None) -> CardPhotoOut | None:
    if ref is None or ref.status != READY or not ref.variants:
        return None
    return CardPhotoOut(
        placeholder=ref.placeholder,
        variants=[
            CardVariantOut(name=v.name, url=v.url, width=v.width, height=v.height)
            for v in ref.variants
        ],
        video_url=ref.video_url,
        duration_ms=ref.duration_ms,
    )


async def _works(media: MediaApi, works: tuple[PublicWork, ...]) -> list[CardWorkOut]:
    """Работы с готовыми файлами по порядку: обрабатываемые и сбойные клиенту не видны."""
    refs = await media.refs([work.media_id for work in works]) if works else {}
    return _ready_works(refs, works)


def _ready_works(
    refs: Mapping[MediaId, MediaRef], works: tuple[PublicWork, ...]
) -> list[CardWorkOut]:
    shown: list[CardWorkOut] = []
    for work in works:
        photo = _photo(refs.get(work.media_id))
        if photo is not None:
            shown.append(CardWorkOut(id=work.id, kind=work.kind, caption=work.caption, photo=photo))
    return shown


def _money(amount: int | None) -> MoneyOut | None:
    return MoneyOut.of(Money(amount, Currency.RSD)) if amount is not None else None


def _service(service: PublicService) -> CardServiceOut:
    return CardServiceOut(
        id=service.id,
        title=service.title,
        description=service.description,
        category_id=service.category_id,
        price_type=service.price_type,
        price_min=_money(service.price_min),
        price_max=_money(service.price_max),
        unit=service.unit,
        duration_min=service.duration_min,
    )


async def _categories(
    catalog: CatalogApi, ids: list[CategoryId], locale: Locale
) -> list[CardNamedOut]:
    found = {category.id: category for category in await catalog.categories(ids)}
    return [
        CardNamedOut(id=category_id, name=found[category_id].name.get(locale))
        for category_id in ids
        if category_id in found
    ]


async def _areas(geo: GeoApi, ids: tuple[DistrictId, ...], locale: Locale) -> list[CardNamedOut]:
    """Районы по порядку профиля — пачкой из справочника."""
    found = await geo.districts(ids) if ids else {}
    return [
        CardNamedOut(id=district.id, name=district.name.get(locale))
        for district in (found.get(district_id) for district_id in ids)
        if district is not None
    ]


def _avatar_ids(profile: PublicProfile) -> list[MediaId]:
    return [profile.avatar_media_id] if profile.avatar_media_id is not None else []


@router.get(
    "/specialists/{profile_id}",
    response_model=SpecialistProfileOut,
    responses=NOT_MODIFIED,
    dependencies=profile_limit,
)
@inject
async def get_specialist(
    *,
    request: Request,
    profile_id: ProfileId,
    specialists: FromDishka[SpecialistsApi],
    identity: FromDishka[IdentityApi],
    pricing: FromDishka[PricingApi],
    media: FromDishka[MediaApi],
    reviews: FromDishka[ReviewsApi],
    catalog: FromDishka[CatalogApi],
    geo: FromDishka[GeoApi],
    search: FromDishka[SearchApi],
    clock: FromDishka[Clock],
    locale: FromDishka[Locale],
) -> Response:
    """Карточка специалиста S08: профиль, первые позиции прайса, превью портфолио, рейтинг и
    время ответа."""
    profile = await _visible(profile_id, specialists, identity)
    rating = _rating((await reviews.summaries([profile.id])).get(profile.id))
    latest = await reviews.reviews_of(profile.id, PageRequest(limit=LATEST_REVIEWS))
    services = await pricing.public_services(profile.id)
    # фото профиля и работы — одним запросом; готовность всех работ нужна для works_count
    avatars = await media.refs([*_avatar_ids(profile), *(work.media_id for work in profile.works)])
    works = _ready_works(avatars, profile.works)
    city = await geo.city(profile.city_id)
    areas = await _areas(geo, profile.area_ids, locale)
    until = profile.available_until
    body = SpecialistProfileOut(
        id=profile.id,
        kind=profile.kind,
        display_name=profile.display_name,
        headline=profile.headline,
        about=profile.about,
        avatar=_photo(avatars.get(profile.avatar_media_id)) if profile.avatar_media_id else None,
        city=CardNamedOut(id=city.id, name=city.name.get(locale)) if city is not None else None,
        district=areas[0] if areas else None,
        areas=areas,
        travel_radius_km=profile.travel_radius_km,
        work_modes=list(profile.work_modes),
        languages=list(profile.languages),
        categories=await _categories(catalog, list(profile.category_ids), locale),
        available_until=until if until is not None and until > clock.now() else None,
        is_founding=profile.is_founding,
        rating=rating.rating,
        rating_count=rating.count,
        is_new=rating.is_new,
        badges=[],
        response_time_minutes=await search.response_time(profile.id),
        services=[_service(service) for service in services[:TOP_SERVICES]],
        services_count=len(services),
        works=works[:PREVIEW_WORKS],
        works_count=len(works),
        reviews=await _review_cards(latest.items, identity, catalog, locale),
        published_at=profile.published_at,
    )
    return _cached(request, body)


@router.get(
    "/specialists/{profile_id}/services",
    response_model=CardServicesOut,
    responses=NOT_MODIFIED,
    dependencies=profile_limit,
)
@inject
async def list_specialist_services(
    *,
    request: Request,
    profile_id: ProfileId,
    specialists: FromDishka[SpecialistsApi],
    identity: FromDishka[IdentityApi],
    pricing: FromDishka[PricingApi],
    catalog: FromDishka[CatalogApi],
    locale: FromDishka[Locale],
) -> Response:
    """Прайс специалиста S09: все видимые позиции и их группы (категории)."""
    profile = await _visible_card(profile_id, specialists, identity)
    services = await pricing.public_services(profile.id)
    groups = list(dict.fromkeys(s.category_id for s in services if s.category_id is not None))
    body = CardServicesOut(
        items=[_service(service) for service in services],
        categories=await _categories(catalog, groups, locale),
    )
    return _cached(request, body)


@router.get(
    "/specialists/{profile_id}/portfolio",
    response_model=CardWorksOut,
    responses=NOT_MODIFIED,
    dependencies=profile_limit,
)
@inject
async def list_specialist_works(
    *,
    request: Request,
    profile_id: ProfileId,
    specialists: FromDishka[SpecialistsApi],
    identity: FromDishka[IdentityApi],
    media: FromDishka[MediaApi],
) -> Response:
    """Портфолио специалиста S10: все работы с готовыми файлами, по порядку."""
    profile = await _visible(profile_id, specialists, identity)
    body = CardWorksOut(items=await _works(media, profile.works))
    return _cached(request, body)


@router.get(
    "/specialists/{profile_id}/reviews",
    response_model=CardReviewsOut,
    responses=NOT_MODIFIED,
    dependencies=profile_limit,
)
@inject
async def list_specialist_reviews(
    *,
    request: Request,
    profile_id: ProfileId,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    specialists: FromDishka[SpecialistsApi],
    identity: FromDishka[IdentityApi],
    reviews: FromDishka[ReviewsApi],
    catalog: FromDishka[CatalogApi],
    locale: FromDishka[Locale],
) -> Response:
    """Отзывы S11: рейтинг с гистограммой и опубликованные отзывы по сделкам с ответами,
    новые первыми (курсор). Вкладка «До платформы» (`kind`) — 7.6."""
    profile = await _visible_card(profile_id, specialists, identity)
    summary = (await reviews.summaries([profile.id])).get(profile.id)
    page = await reviews.reviews_of(profile.id, PageRequest(limit=limit, cursor=cursor))
    body = CardReviewsOut(
        summary=_rating(summary),
        items=await _review_cards(page.items, identity, catalog, locale),
        next_cursor=page.next_cursor,
    )
    return _cached(request, body)


async def _review_cards(
    found: tuple[PublicReview, ...],
    identity: IdentityApi,
    catalog: CatalogApi,
    locale: Locale,
) -> list[CardReviewOut]:
    """Отзывы карточкой: автор — «Имя Ф.», услуга — название категории сделки."""
    if not found:
        return []
    users = await identity.users({review.author_id for review in found})
    ids = sorted({CategoryId(r.category_id) for r in found if r.category_id is not None})
    categories = {c.id: c for c in await _categories(catalog, ids, locale)}
    cards: list[CardReviewOut] = []
    for review in found:
        author = users.get(review.author_id)
        reply = review.reply
        cards.append(
            CardReviewOut(
                id=review.id,
                kind=review.kind,
                author_name=(
                    short_name(author.display_name)
                    if author is not None and not author.is_deleted
                    else ""
                ),
                rating=review.rating,
                criteria=dict(review.criteria),
                body=review.body,
                category=(
                    categories.get(CategoryId(review.category_id))
                    if review.category_id is not None
                    else None
                ),
                published_at=review.published_at,
                reply=CardReplyOut(body=reply.body, at=reply.at) if reply is not None else None,
            )
        )
    return cards


def _rating(summary: RatingSummary | None) -> CardRatingOut:
    """Рейтинг для показа: «Новый специалист», пока отзывов меньше трёх."""
    if summary is None:
        return CardRatingOut(
            rating=None, count=0, is_new=True, distribution=[0] * STARS, criteria={}
        )
    return CardRatingOut(
        rating=None if summary.is_new else round(summary.average, 1),
        count=summary.count,
        is_new=summary.is_new,
        distribution=list(summary.distribution),
        criteria=dict(summary.criteria),
    )


def _cached(request: Request, body: BaseModel) -> Response:
    payload: Any = body.model_dump(mode="json")
    return cached_json(request, payload, max_age=MAX_AGE_SECONDS, vary="Accept-Language")
