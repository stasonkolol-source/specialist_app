"""Admin API geo (DEVELOPMENT_PLAN 2.7b, часть 2; ARCHITECTURE §8.5): города и районы.

Только admin. Правится то же, что в разделах SQLAdmin (admin/views.py), и тем же путём —
`apply_change` с хуками раздела: запуск города (`is_active`) и порядок городов, включён ли район,
названия формой LocalizedText (`name_origin = admin` — `cli seed` его больше не переписывает);
advisory lock импорта городов, аудит `geo.city|district.updated`, сброс снимка справочника.
Центры и границы принадлежат сидам и в ответ не идут. События изменения у geo нет.
"""

from typing import Annotated, Any

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.geo.admin.views import CityAdmin, DistrictAdmin
from app.platform.http.admin import ADMIN, AdminRows, apply_change, as_row, table_of
from app.platform.http.pagination import PageOut, PageParams
from app.platform.http.staff import staff_only
from app.platform.kernel.errors import NotFoundError
from app.platform.kernel.localized import Locale

router = APIRouter(tags=["geo"])

NameIn = dict[Locale, Annotated[str, Field(max_length=120)]]
CITY_COLUMNS = ("id", "slug", "name", "name_origin", "is_active", "sort_order")
DISTRICT_COLUMNS = (
    "id",
    "city_id",
    "parent_id",
    "kind",
    "slug",
    "name",
    "name_origin",
    "is_active",
)


class CityOut(BaseModel):
    id: int
    slug: str
    name: dict[str, str]
    name_origin: str
    is_active: bool = Field(description="Город запущен: виден в онбординге и поиске")
    sort_order: int

    @classmethod
    def of(cls, row: Any) -> CityOut:
        return cls(**_plain(row, CITY_COLUMNS))


class CityPatchIn(BaseModel):
    is_active: Annotated[bool | None, Query()] = None
    sort_order: int | None = None
    name: NameIn | None = None


class DistrictOut(BaseModel):
    id: int
    city_id: int
    parent_id: int | None
    kind: str
    slug: str
    name: dict[str, str]
    name_origin: str
    is_active: bool

    @classmethod
    def of(cls, row: Any) -> DistrictOut:
        return cls(**_plain(row, DISTRICT_COLUMNS))


class DistrictPatchIn(BaseModel):
    is_active: Annotated[bool | None, Query()] = None
    name: NameIn | None = None


@router.get("/cities", response_model=PageOut[CityOut], **staff_only(ADMIN))
@inject
async def list_cities(
    page: PageParams,
    session: FromDishka[AsyncSession],
    is_active: Annotated[bool | None, Query()] = None,
) -> PageOut[CityOut]:
    table = table_of(CityAdmin)
    where = [table.c.is_active.is_(is_active)] if is_active is not None else []
    found = await AdminRows(session).page(table, page, *where, columns=CITY_COLUMNS)
    return PageOut.of(found, CityOut.of)


@router.patch("/cities/{city_id}", response_model=CityOut, **staff_only(ADMIN))
async def update_city(city_id: int, body: CityPatchIn, request: Request) -> CityOut:
    """Запустить или выключить город, порядок, название — аудит и сброс снимка справочника."""
    model = await apply_change(
        request,
        CityAdmin(),
        city_id,
        body.model_dump(exclude_unset=True, exclude={"name"}),
        name=body.name,
    )
    if model is None:
        raise NotFoundError(city_id=city_id)
    return CityOut.of(as_row(model))


@router.get("/districts", response_model=PageOut[DistrictOut], **staff_only(ADMIN))
@inject
async def list_districts(
    page: PageParams,
    session: FromDishka[AsyncSession],
    city_id: int | None = None,
    is_active: Annotated[bool | None, Query()] = None,
) -> PageOut[DistrictOut]:
    table = table_of(DistrictAdmin)
    where = []
    if city_id is not None:
        where.append(table.c.city_id == city_id)
    if is_active is not None:
        where.append(table.c.is_active.is_(is_active))
    found = await AdminRows(session).page(table, page, *where, columns=DISTRICT_COLUMNS)
    return PageOut.of(found, DistrictOut.of)


@router.patch("/districts/{district_id}", response_model=DistrictOut, **staff_only(ADMIN))
async def update_district(district_id: int, body: DistrictPatchIn, request: Request) -> DistrictOut:
    model = await apply_change(
        request,
        DistrictAdmin(),
        district_id,
        body.model_dump(exclude_unset=True, exclude={"name"}),
        name=body.name,
    )
    if model is None:
        raise NotFoundError(district_id=district_id)
    return DistrictOut.of(as_row(model))


def _plain(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    values: dict[str, Any] = {key: getattr(row[key], "value", row[key]) for key in columns}
    values["name"] = row["name"].to_mapping()
    return values
