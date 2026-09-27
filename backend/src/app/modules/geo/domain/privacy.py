"""Публичная точка (ARCHITECTURE §7.6 «Приватность локации»).

Точный адрес заявки или базы специалиста наружу не отдаётся: публичная точка смещена на
300–500 м в направлении и на расстояние, которые детерминированно выводятся из seed
(id сущности). Поэтому точка стабильна между запросами, а усреднение нескольких выдач
одной сущности не приближает к адресу.
"""

import hashlib
import math

from app.platform.kernel.geo import GeoPoint

EARTH_RADIUS_M = 6_371_008.8
MIN_OFFSET_M = 300.0
MAX_OFFSET_M = 500.0


def _fraction(chunk: bytes) -> float:
    return int.from_bytes(chunk) / float(1 << (8 * len(chunk)))


def blur(point: GeoPoint, *, seed: bytes) -> GeoPoint:
    digest = hashlib.sha256(b"geo.public_point:" + seed).digest()
    bearing = 2 * math.pi * _fraction(digest[:8])
    distance = MIN_OFFSET_M + (MAX_OFFSET_M - MIN_OFFSET_M) * _fraction(digest[8:16])
    return destination(point, bearing=bearing, distance_m=distance)


def destination(point: GeoPoint, *, bearing: float, distance_m: float) -> GeoPoint:
    """Точка на расстоянии distance_m по азимуту bearing (радианы), сферическая Земля."""
    lat1, lon1 = math.radians(point.lat), math.radians(point.lon)
    delta = distance_m / EARTH_RADIUS_M
    lat2 = math.asin(
        math.sin(lat1) * math.cos(delta) + math.cos(lat1) * math.sin(delta) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(delta) * math.cos(lat1),
        math.cos(delta) - math.sin(lat1) * math.sin(lat2),
    )
    lon = (math.degrees(lon2) + 540) % 360 - 180
    return GeoPoint(lat=round(math.degrees(lat2), 6), lon=round(lon, 6))


def distance_m(a: GeoPoint, b: GeoPoint) -> float:
    """Расстояние по большой окружности (haversine), метры."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = lat2 - lat1, math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))
