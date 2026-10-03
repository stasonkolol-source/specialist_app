"""HTTP geo 🔓 (DEVELOPMENT_PLAN 1.3a): города, районы, район точки.

Списки городов и районов — из снимка справочника в памяти процесса, тело и ETag строятся раз
на снимок и язык: повторный запрос без изменений — 304 без работы."""

from typing import Annotated

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Path, Query, Request, Response

from app.modules.geo.application.dto import CityView, DistrictView
from app.modules.geo.application.ports import GeoQuery
from app.modules.geo.errors import CityNotFoundError, OutsideServiceAreaError
from app.modules.geo.http.schemas import CityOut, DistrictOut, DistrictRefOut, PointOut, ResolveOut
from app.platform.http.caching import (
    DICTIONARY_SWR,
    NOT_MODIFIED,
    EncodedJson,
    cached_response,
    encode_json,
)
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId
from app.platform.kernel.localized import Locale

router = APIRouter(tags=["geo"])
INT4_MAX = 2**31 - 1
"""id справочников — int4 identity: больше — не id, а 422 (иначе ошибка БД и 500)."""
MAX_AGE_SECONDS = 300


@router.get("/cities", response_model=list[CityOut], responses=NOT_MODIFIED)
@inject
async def list_cities(
    request: Request, query: FromDishka[GeoQuery], locale: FromDishka[Locale]
) -> Response:
    """Города: активные и со статусом «скоро»."""
    # представления — до данных: обновись снимок между ними, тело уйдёт в память старого
    memo = await query.representations()
    cities = await query.cities()
    body = memo.get(("cities", locale), lambda: _cities(cities, locale))
    return _cached(request, body)


@router.get("/cities/{city_id}/districts", response_model=list[DistrictOut], responses=NOT_MODIFIED)
@inject
async def list_districts(
    request: Request,
    city_id: Annotated[int, Path(ge=1, le=INT4_MAX)],
    query: FromDishka[GeoQuery],
    locale: FromDishka[Locale],
) -> Response:
    memo = await query.representations()
    if await query.city(CityId(city_id)) is None:
        raise CityNotFoundError(city_id=city_id)
    districts = await query.districts(CityId(city_id))
    body = memo.get(("districts", city_id, locale), lambda: _districts(districts, locale))
    return _cached(request, body)


def _cities(cities: list[CityView], locale: Locale) -> EncodedJson:
    return encode_json(
        [
            CityOut(
                id=city.id,
                slug=city.slug,
                name=city.name.get(locale),
                status=city.status,
                center=PointOut.of(city.center),
            ).model_dump(mode="json")
            for city in cities
        ]
    )


def _districts(districts: list[DistrictView], locale: Locale) -> EncodedJson:
    return encode_json(
        [
            DistrictOut(
                id=d.id,
                slug=d.slug,
                name=d.name.get(locale),
                kind=d.kind,
                parent_id=d.parent_id,
                center=PointOut.of(d.center),
            ).model_dump(mode="json")
            for d in districts
        ]
    )


def _cached(request: Request, body: EncodedJson) -> Response:
    """ETag + If-None-Match → 304; справочник можно показывать из кэша, пока он проверяется."""
    return cached_response(
        request,
        body,
        max_age=MAX_AGE_SECONDS,
        vary="Accept-Language",
        stale_while_revalidate=DICTIONARY_SWR,
    )


@router.get("/geo/resolve")
@inject
async def resolve_point(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    query: FromDishka[GeoQuery],
    locale: FromDishka[Locale],
) -> ResolveOut:
    """Район точки: внутри полигона или ближайший центр района не дальше 15 км."""
    resolved = await query.resolve(GeoPoint(lat=lat, lon=lon))
    if resolved is None:
        raise OutsideServiceAreaError
    district = resolved.district
    return ResolveOut(
        city_id=district.city_id,
        district=DistrictRefOut(id=district.id, slug=district.slug, name=district.name.get(locale)),
        exact=resolved.exact,
    )
