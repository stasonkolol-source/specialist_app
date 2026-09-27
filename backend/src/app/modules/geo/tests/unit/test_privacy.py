"""Публичная точка: 300–500 м, детерминированно (ARCHITECTURE §7.6)."""

import pytest

from app.modules.geo.domain.privacy import MAX_OFFSET_M, MIN_OFFSET_M, blur, destination, distance_m
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import new_id

pytestmark = pytest.mark.unit

LIMAN = GeoPoint(lat=45.2445, lon=19.8395)


def test_public_point_is_300_to_500_m_away() -> None:
    for _ in range(500):
        public = blur(LIMAN, seed=new_id().bytes)
        assert MIN_OFFSET_M - 1 <= distance_m(LIMAN, public) <= MAX_OFFSET_M + 1


def test_public_point_is_stable_per_seed_and_differs_between_seeds() -> None:
    seed = new_id().bytes
    assert blur(LIMAN, seed=seed) == blur(LIMAN, seed=seed)
    points = {blur(LIMAN, seed=new_id().bytes) for _ in range(50)}
    assert len(points) == 50


def test_directions_cover_all_sides() -> None:
    publics = [blur(LIMAN, seed=new_id().bytes) for _ in range(200)]
    assert any(p.lat > LIMAN.lat for p in publics)
    assert any(p.lat < LIMAN.lat for p in publics)
    assert any(p.lon > LIMAN.lon for p in publics)
    assert any(p.lon < LIMAN.lon for p in publics)


@pytest.mark.parametrize("bearing", [0.0, 1.57, 3.14, 4.71])
def test_destination_matches_haversine(bearing: float) -> None:
    point = destination(LIMAN, bearing=bearing, distance_m=400)
    assert abs(distance_m(LIMAN, point) - 400) < 0.5


def test_destination_wraps_longitude() -> None:
    edge = GeoPoint(lat=0.0, lon=179.9999)
    assert -180 <= destination(edge, bearing=1.57, distance_m=500).lon <= 180
