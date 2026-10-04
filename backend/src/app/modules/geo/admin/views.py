"""Города и районы в админке (DEVELOPMENT_PLAN 2.7b; ADR-0020 §1).

Правится только то, что сид задаёт при вставке: включён ли город (запуск города — флаг
`is_active`) и район, порядок городов. Названия, центры и границы принадлежат сидам (`cli seed`) —
в админке только для чтения. Запись берёт advisory lock импорта городов; каждая правка — в
audit_log; снимок справочника этого процесса сбрасывается сразу, у остальных — за TTL. События
изменения у geo нет (подписчиков нет: поиск читает районы при переиндексации профиля).
"""

from typing import Any, ClassVar, override

from starlette.requests import Request

from app.modules.geo.application.ports import DirectoryCache
from app.modules.geo.infrastructure.models import IMPORT_LOCK, CityRow, DistrictRow
from app.platform.http.admin import ADMIN, StaffModelView, container_of


class _GeoView(StaffModelView):
    roles = ADMIN
    advisory_lock = IMPORT_LOCK
    category = "Справочники"
    can_create = can_delete = False

    @override
    async def after_change(self, model: Any, request: Request) -> None:
        (await container_of(request).get(DirectoryCache)).invalidate()


class CityAdmin(_GeoView, model=CityRow):
    name = "Город"
    name_plural = "Города"
    icon = "fa-solid fa-city"
    audit_entity = "geo.city"
    column_list: ClassVar[Any] = [
        CityRow.id,
        CityRow.slug,
        CityRow.name,
        CityRow.is_active,
        CityRow.sort_order,
    ]
    column_details_list: ClassVar[Any] = column_list
    form_columns: ClassVar[Any] = [CityRow.is_active, CityRow.sort_order]


class DistrictAdmin(_GeoView, model=DistrictRow):
    name = "Район"
    name_plural = "Районы"
    icon = "fa-solid fa-map"
    audit_entity = "geo.district"
    column_list: ClassVar[Any] = [
        DistrictRow.id,
        DistrictRow.city_id,
        DistrictRow.kind,
        DistrictRow.slug,
        DistrictRow.name,
        DistrictRow.is_active,
    ]
    column_details_list: ClassVar[Any] = column_list
    column_searchable_list: ClassVar[Any] = [DistrictRow.slug]
    form_columns: ClassVar[Any] = [DistrictRow.is_active]


VIEWS = (CityAdmin, DistrictAdmin)
