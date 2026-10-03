"""Контракт модуля geo для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из geo только этот файл.
"""

from collections.abc import Collection
from dataclasses import dataclass
from typing import Protocol

from app.modules.geo.errors import CityNotFoundError as CityNotFoundError
from app.modules.geo.errors import OutsideServiceAreaError as OutsideServiceAreaError
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId, DistrictId
from app.platform.kernel.localized import LocalizedText


@dataclass(frozen=True, slots=True, kw_only=True)
class CitySummary:
    id: CityId
    slug: str
    name: LocalizedText
    is_active: bool
    """False — город со статусом «скоро»: виден в списке, выбрать его ещё нельзя."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DistrictSummary:
    id: DistrictId
    city_id: CityId
    slug: str
    name: LocalizedText
    center: GeoPoint


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedPoint:
    district: DistrictSummary
    exact: bool
    """True — точка внутри полигона района; False — взят ближайший центр района."""


class GeoApi(Protocol):
    async def city(self, city_id: CityId) -> CitySummary | None:
        """Город справочника; None — такого нет (identity проверяет город из онбординга)."""
        ...

    async def resolve(self, point: GeoPoint) -> ResolvedPoint | None:
        """Район точки; None — точка вне зоны сервиса."""
        ...

    async def district(self, district_id: DistrictId) -> DistrictSummary | None: ...

    async def districts(
        self, district_ids: Collection[DistrictId]
    ) -> dict[DistrictId, DistrictSummary]:
        """Районы пачкой — карточки BFF (S08, S23); кого нет — нет и в ответе."""
        ...

    def public_point(self, point: GeoPoint, *, seed: bytes) -> GeoPoint:
        """Смещённая на 300–500 м точка, стабильная для одного seed (id сущности)."""
        ...
