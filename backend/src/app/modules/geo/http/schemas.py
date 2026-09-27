"""Схемы HTTP geo: названия — одной строкой на языке Accept-Language (ARCHITECTURE §8.1)."""

from pydantic import BaseModel

from app.modules.geo.domain.place import CityStatus, DistrictKind
from app.platform.kernel.geo import GeoPoint


class PointOut(BaseModel):
    lat: float
    lon: float

    @classmethod
    def of(cls, point: GeoPoint) -> PointOut:
        return cls(lat=point.lat, lon=point.lon)


class CityOut(BaseModel):
    id: int
    slug: str
    name: str
    status: CityStatus
    """`soon` — город виден в списке, но выбрать его пока нельзя."""
    center: PointOut


class DistrictOut(BaseModel):
    id: int
    slug: str
    name: str
    kind: DistrictKind
    parent_id: int | None
    center: PointOut


class DistrictRefOut(BaseModel):
    id: int
    slug: str
    name: str


class ResolveOut(BaseModel):
    city_id: int
    district: DistrictRefOut
    exact: bool
    """true — точка внутри полигона района; false — ближайший центр района."""
