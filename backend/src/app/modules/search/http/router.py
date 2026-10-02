"""HTTP search 🔓 (DEVELOPMENT_PLAN 4.2): выдача специалистов S05 с фильтрами шторки S06.

Каталог открыт и гостю. Лимит — 60 запросов в минуту на адрес гостя и 120 на вошедшего
(ARCHITECTURE §13.3). Порядок, этапы поиска и пустая выдача — в use case.
"""

from typing import Annotated, Literal

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Query, Response

from app.modules.search.application.dto import SpecialistFilters
from app.modules.search.application.use_cases.search_specialists import (
    SearchSpecialists,
    SearchSpecialistsCommand,
)
from app.modules.search.domain.query import MAX_QUERY, SpecialistSort
from app.modules.search.http.schemas import SpecialistPageOut
from app.platform.http.pagination import PageParams
from app.platform.http.ratelimit import GuestOrUserRateLimit
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId
from app.platform.kernel.localized import Locale
from app.platform.ratelimit import Rate

SEARCH_GUEST = Rate("search.guest", "60/minute")
SEARCH_USER = Rate("search.user", "120/minute")
METERS_IN_KM = 1000
MAX_LISTED = 20
"""Районов, языков, форматов в одном фильтре — больше в шторке не выбрать."""

router = APIRouter(tags=["search"])
search_limit = [Depends(GuestOrUserRateLimit(guest=SEARCH_GUEST, user=SEARCH_USER))]


def specialist_filters(
    *,
    city_id: Annotated[CityId, Query(ge=1, description="Город выдачи")],
    category_id: Annotated[CategoryId | None, Query(ge=1, description="С подкатегориями")] = None,
    district_ids: Annotated[list[DistrictId] | None, Query(max_length=MAX_LISTED)] = None,
    lat: Annotated[float | None, Query(ge=-90, le=90, description="Точка клиента")] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[int | None, Query(ge=1, le=50, description="Нужна точка")] = None,
    travels_to_me: Annotated[
        bool, Query(description="Выезжает к точке клиента (его радиус выезда)")
    ] = False,
    price_max: Annotated[int | None, Query(ge=0, description="Цена «до», пара")] = None,
    rating_min: Annotated[float | None, Query(ge=1, le=5)] = None,
    languages: Annotated[
        list[str] | None, Query(max_length=MAX_LISTED, description="ru, sr, en, uk")
    ] = None,
    work_modes: Annotated[
        list[Literal["at_client", "at_own_place", "remote"]] | None,
        Query(max_length=MAX_LISTED),
    ] = None,
    available_today: Annotated[bool, Query()] = False,
    verified: Annotated[bool, Query(description="С подтверждённым телефоном (v1)")] = False,
    with_reviews: Annotated[bool, Query()] = False,
    kind: Annotated[
        Literal["pro", "casual"], Query(description="«Подработка» — только явно")
    ] = "pro",
) -> SpecialistFilters:
    if (lat is None) != (lon is None):
        raise DomainValidationError(field="lat" if lat is None else "lon", reason="pair")
    return SpecialistFilters(
        city_id=city_id,
        kind=kind,
        category_id=category_id,
        district_ids=tuple(district_ids or ()),
        point=GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None,
        radius_m=radius_km * METERS_IN_KM if radius_km else None,
        travels_to_me=travels_to_me,
        price_max=price_max,
        rating_min=rating_min,
        languages=tuple(languages or ()),
        work_modes=tuple(work_modes or ()),
        available_today=available_today,
        verified=verified,
        with_reviews=with_reviews,
    )


@router.get("/specialists", response_model=SpecialistPageOut, dependencies=search_limit)
@inject
async def list_specialists(
    *,
    response: Response,
    search: FromDishka[SearchSpecialists],
    locale: FromDishka[Locale],
    filters: Annotated[SpecialistFilters, Depends(specialist_filters)],
    page: PageParams,
    q: Annotated[
        str | None, Query(max_length=2 * MAX_QUERY, description="Текст: ru, sr, en, с опечатками")
    ] = None,
    sort: Annotated[
        SpecialistSort, Query(description="distance — нужна точка клиента")
    ] = SpecialistSort.RELEVANCE,
    urgent: Annotated[bool, Query(description="«Срочно»: доступные сегодня — выше")] = False,
) -> SpecialistPageOut:
    """Выдача специалистов: текст, фильтры, порядок; карточки готовы к показу."""
    results = await search(
        SearchSpecialistsCommand(
            filters=filters, q=q, sort=sort, page=page, locale=locale.value, urgent=urgent
        )
    )
    response.headers["Vary"] = "Accept-Language"
    return SpecialistPageOut.from_results(results, locale)
