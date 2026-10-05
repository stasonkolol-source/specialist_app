"""Read-DTO и данные импорта справочника geo (ADR-0020 §3)."""

from dataclasses import dataclass

from app.modules.geo.domain.place import CityStatus, DistrictKind
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CityId, DistrictId
from app.platform.kernel.localized import LocalizedText


@dataclass(frozen=True, slots=True, kw_only=True)
class CityView:
    id: CityId
    slug: str
    name: LocalizedText
    center: GeoPoint
    status: CityStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class DistrictView:
    id: DistrictId
    city_id: CityId
    parent_id: DistrictId | None
    kind: DistrictKind
    slug: str
    name: LocalizedText
    center: GeoPoint


@dataclass(frozen=True, slots=True, kw_only=True)
class LocatedDistrict:
    """Район города по точке клиента (S20b «Определить по геолокации», булавка на карте)."""

    district: DistrictView
    exact: bool
    """True — точка внутри района; False — точка у края города, взят ближайший район."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DistrictSeed:
    slug: str
    kind: DistrictKind
    parent: str | None
    name: LocalizedText
    aliases: tuple[str, ...]
    center: GeoPoint
    boundary_wkt: str | None
    """MULTIPOLYGON в WKT (WGS 84); None — у района нет полигона."""
    source: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CitySeed:
    slug: str
    name: LocalizedText
    center: GeoPoint
    active: bool
    sort_order: int
    boundary_wkt: str | None
    districts: tuple[DistrictSeed, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportResult:
    created: int
    updated: int
    unchanged: int
