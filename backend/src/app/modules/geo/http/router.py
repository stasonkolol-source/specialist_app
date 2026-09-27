"""HTTP geo 🔓 (DEVELOPMENT_PLAN 1.3a): города, районы, район точки."""

from typing import Annotated

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Path, Query, Response

from app.modules.geo.application.ports import GeoQuery
from app.modules.geo.errors import CityNotFoundError, OutsideServiceAreaError
from app.modules.geo.http.schemas import CityOut, DistrictOut, DistrictRefOut, PointOut, ResolveOut
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId
from app.platform.kernel.localized import Locale

router = APIRouter(tags=["geo"])
INT4_MAX = 2**31 - 1
"""id справочников — int4 identity: больше — не id, а 422 (иначе ошибка БД и 500)."""
CACHE = {"Cache-Control": "public, max-age=300", "Vary": "Accept-Language"}


@router.get("/cities")
@inject
async def list_cities(
    query: FromDishka[GeoQuery], locale: FromDishka[Locale], response: Response
) -> list[CityOut]:
    """Города: активные и со статусом «скоро»."""
    response.headers.update(CACHE)
    return [
        CityOut(
            id=city.id,
            slug=city.slug,
            name=city.name.get(locale),
            status=city.status,
            center=PointOut.of(city.center),
        )
        for city in await query.cities()
    ]


@router.get("/cities/{city_id}/districts")
@inject
async def list_districts(
    city_id: Annotated[int, Path(ge=1, le=INT4_MAX)],
    query: FromDishka[GeoQuery],
    locale: FromDishka[Locale],
    response: Response,
) -> list[DistrictOut]:
    if await query.city(CityId(city_id)) is None:
        raise CityNotFoundError(city_id=city_id)
    response.headers.update(CACHE)
    return [
        DistrictOut(
            id=d.id,
            slug=d.slug,
            name=d.name.get(locale),
            kind=d.kind,
            parent_id=d.parent_id,
            center=PointOut.of(d.center),
        )
        for d in await query.districts(CityId(city_id))
    ]


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
