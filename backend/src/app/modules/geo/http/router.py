"""HTTP geo 🔓 (DEVELOPMENT_PLAN 1.3a): города, районы, район точки.

Списки городов и районов — из снимка справочника в памяти процесса, тело и ETag строятся раз
на снимок и язык: повторный запрос без изменений — 304 без работы. Район по точке клиента
(`/geo/districts/locate`, S20b и карта) — только вошедшему и с лимитом: координаты не
сохраняются и не логируются (use case locate_district)."""

from typing import Annotated

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, Path, Query, Request, Response

from app.modules.geo.application.dto import CityView, DistrictView
from app.modules.geo.application.ports import GeoQuery
from app.modules.geo.application.use_cases.locate_district import (
    LocateDistrict,
    LocateDistrictCommand,
)
from app.modules.geo.errors import CityNotFoundError, OutsideServiceAreaError
from app.modules.geo.http.schemas import CityOut, DistrictOut, DistrictRefOut, PointOut, ResolveOut
from app.platform.http.caching import (
    DICTIONARY_SWR,
    EncodedJson,
    cached_response,
    encode_json,
)
from app.platform.http.ratelimit import RateLimit
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId
from app.platform.kernel.localized import Locale
from app.platform.ratelimit import Rate

router = APIRouter(tags=["geo"])
INT4_MAX = 2**31 - 1
"""id справочников — int4 identity: больше — не id, а 422 (иначе ошибка БД и 500)."""
MAX_AGE_SECONDS = 300
LOCATE_PER_USER = Rate("geo.locate", "60/minute")
"""Район по точке: кнопка «Определить по геолокации» и булавка на карте — с запасом на перенос
булавки, но не сканер районов по сетке точек."""


# 304 в схему не внесён: его получает HTTP-кэш браузера, клиенту приходит 200 из кэша, а
# сгенерированный клиент без изменений контракта
@router.get("/cities", response_model=list[CityOut])
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


@router.get("/cities/{city_id}/districts", response_model=list[DistrictOut])
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


@router.get(
    "/geo/districts/locate",
    response_model=DistrictOut,
    dependencies=[*AUTHENTICATED, Depends(RateLimit(LOCATE_PER_USER))],
)
@inject
async def locate_district(
    city_id: Annotated[int, Query(ge=1, le=INT4_MAX)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    locate: FromDishka[LocateDistrict],
    locale: FromDishka[Locale],
) -> DistrictOut:
    """Район города по точке клиента (S20b «Определить по геолокации», карта): квартал, в
    котором точка; у края города (до 3 км) — ближайший; дальше — 404 `outside_city`.
    Координаты не сохраняются и не пишутся в лог: в логе только район и исход."""
    district = await locate(
        LocateDistrictCommand(city_id=CityId(city_id), point=GeoPoint(lat=lat, lon=lon))
    )
    return _district_out(district, locale)


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
    return encode_json([_district_out(d, locale).model_dump(mode="json") for d in districts])


def _district_out(district: DistrictView, locale: Locale) -> DistrictOut:
    """Один вид района у списка и у района по точке: клиент сверяет их по id."""
    return DistrictOut(
        id=district.id,
        slug=district.slug,
        name=district.name.get(locale),
        kind=district.kind,
        parent_id=district.parent_id,
        center=PointOut.of(district.center),
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
