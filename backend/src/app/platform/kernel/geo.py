"""Географическая точка (WGS 84). Хранение — geography(POINT, 4326), см. docs/spikes/0.6."""

import math
from dataclasses import dataclass

from app.platform.kernel.errors import DomainValidationError


@dataclass(frozen=True, slots=True)
class GeoPoint:
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.lat) and -90 <= self.lat <= 90):
            raise DomainValidationError(field="lat", value=self.lat)
        if not (math.isfinite(self.lon) and -180 <= self.lon <= 180):
            raise DomainValidationError(field="lon", value=self.lon)

    def to_ewkt(self) -> str:
        """EWKT для PostGIS: порядок координат — долгота, широта."""
        return f"SRID=4326;POINT({self.lon} {self.lat})"
