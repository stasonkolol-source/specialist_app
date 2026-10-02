"""BFF карточки специалиста S08–S10 (DEVELOPMENT_PLAN 4.5): профиль, прайс и портфолио одним
запросом — из фасадов specialists, pricing, media, catalog, geo и identity (ARCHITECTURE §5.2 п. 7).

Профиль виден, если он опубликован, а автор не удалён и не скрыт санкцией — как в поиске;
иначе 404, без подсказки почему. Ответ на языке Accept-Language, с ETag: повторный запрос без
изменений — 304. Фото — готовые варианты; пока файл обрабатывается, его на карточке нет.
Рейтинг и отзывы — с 7.2, «Обычно отвечает за …» — с 6.3b, бейджи — v1: пока пусто.
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Path, Request, Response
from pydantic import BaseModel, Field

from app.modules.catalog.api import CatalogApi
from app.modules.geo.api import GeoApi
from app.modules.identity.api import IdentityApi
from app.modules.media.api import MediaApi, MediaRef
from app.modules.pricing.api import PricingApi, PublicService
from app.modules.specialists.api import PublicProfile, PublicWork, SpecialistsApi
from app.platform.http.caching import NOT_MODIFIED, cached_json
from app.platform.http.money import MoneyOut
from app.platform.http.ratelimit import GuestOrUserRateLimit
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import NotFoundError
from app.platform.kernel.ids import CategoryId, DistrictId, MediaId
from app.platform.kernel.localized import Locale
from app.platform.kernel.money import Currency, Money
from app.platform.ratelimit import Rate

PROFILE_GUEST = Rate("views.specialist_guest", "60/minute")
PROFILE_USER = Rate("views.specialist_user", "120/minute")
"""Карточка — часть каталога: те же 60 / 120 в минуту (ARCHITECTURE §13.3), свои счётчики."""
MAX_AGE_SECONDS = 60
TOP_SERVICES = 3
PREVIEW_WORKS = 3
"""«Цены» и «Работы» на S08 — по одному ряду, как на артборде; остальное — S09 и S10."""
READY = "ready"
NEW_UNTIL_REVIEWS = 3

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
    response_time_minutes: int | None = Field(description="«Обычно отвечает за …» — с 6.3b")
    services: list[CardServiceOut] = Field(description="Первые позиции прайса (S08)")
    services_count: int
    works: list[CardWorkOut] = Field(description="Превью портфолио (S08)")
    works_count: int
    published_at: datetime | None


class CardServicesOut(BaseModel):
    items: list[CardServiceOut]
    categories: list[CardNamedOut] = Field(description="Группы прайса S09 в порядке позиций")


class CardWorksOut(BaseModel):
    items: list[CardWorkOut]


async def _visible(
    profile_id: UUID, specialists: SpecialistsApi, identity: IdentityApi
) -> PublicProfile:
    """Опубликованный профиль автора, которого не скрывает санкция; иначе 404 (как в поиске)."""
    profile = await specialists.public_profile(profile_id)
    if profile is None or await identity.hidden_from_search([profile.user_id]):
        raise NotFoundError()
    return profile


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
    areas: list[CardNamedOut] = []
    for district_id in ids:
        district = await geo.district(district_id)
        if district is not None:
            areas.append(CardNamedOut(id=district.id, name=district.name.get(locale)))
    return areas


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
    catalog: FromDishka[CatalogApi],
    geo: FromDishka[GeoApi],
    clock: FromDishka[Clock],
    locale: FromDishka[Locale],
) -> Response:
    """Карточка специалиста S08: профиль, первые позиции прайса и превью портфолио."""
    profile = await _visible(profile_id, specialists, identity)
    services = await pricing.public_services(profile.id)
    works = await _works(media, profile.works)
    avatars = await media.refs(_avatar_ids(profile))
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
        rating=None,
        rating_count=0,
        is_new=True,
        badges=[],
        response_time_minutes=None,
        services=[_service(service) for service in services[:TOP_SERVICES]],
        services_count=len(services),
        works=works[:PREVIEW_WORKS],
        works_count=len(works),
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
    profile = await _visible(profile_id, specialists, identity)
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


def _cached(request: Request, body: BaseModel) -> Response:
    payload: Any = body.model_dump(mode="json")
    return cached_json(request, payload, max_age=MAX_AGE_SECONDS, vary="Accept-Language")
