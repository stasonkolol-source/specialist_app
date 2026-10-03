"""GET /cities, /cities/{id}/districts, /geo/resolve (DEVELOPMENT_PLAN 1.3a)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.plugins.http import http_app, http_client
from tests.plugins.round_trips import round_trips

from app.modules.geo.http.router import router
from app.platform.settings import Settings

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("geo_seeded")]

LIMAN_3 = {"lat": 45.2397, "lon": 19.8350}


@pytest.fixture
async def api(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with http_client(settings, router) as client:
        yield client


async def _city_id(api: httpx.AsyncClient, slug: str) -> int:
    cities = (await api.get("/api/v1/cities")).json()
    return int(next(c["id"] for c in cities if c["slug"] == slug))


@pytest.mark.parametrize(
    ("language", "novi_sad", "belgrade"),
    [
        ("ru", "Нови-Сад", "Белград"),
        ("sr-Latn", "Novi Sad", "Beograd"),
        ("sr-Cyrl", "Нови Сад", "Београд"),
    ],
)
async def test_cities_are_localized_with_status(
    api: httpx.AsyncClient, language: str, novi_sad: str, belgrade: str
) -> None:
    response = await api.get("/api/v1/cities", headers={"accept-language": language})
    assert response.status_code == 200
    assert response.headers["cache-control"] == (
        "public, max-age=300, stale-while-revalidate=86400"
    )
    assert response.headers["vary"] == "Accept-Language"
    cities = {c["slug"]: c for c in response.json()}
    assert (cities["novi-sad"]["name"], cities["novi-sad"]["status"]) == (novi_sad, "active")
    assert (cities["beograd"]["name"], cities["beograd"]["status"]) == (belgrade, "soon")
    assert set(cities["novi-sad"]["center"]) == {"lat", "lon"}


async def test_districts_of_city(api: httpx.AsyncClient) -> None:
    city_id = await _city_id(api, "novi-sad")
    response = await api.get(
        f"/api/v1/cities/{city_id}/districts", headers={"accept-language": "sr-Latn"}
    )
    districts = {d["slug"]: d for d in response.json()}
    assert len(districts) == 28
    assert districts["novi-sad"]["kind"] == "municipality"
    assert districts["liman-3"]["parent_id"] == districts["novi-sad"]["id"]
    assert districts["adamovicevo-naselje"]["name"] == "Adamovićevo naselje"
    missing = await api.get("/api/v1/cities/999999/districts")
    assert missing.status_code == 404
    assert missing.json()["code"] == "city_not_found"


async def test_dictionary_answers_304_from_memory(settings: Settings) -> None:
    """Перф-аудит: города и районы — из снимка в памяти процесса; тот же ETag — 304, а
    повторные запросы в базу не ходят (снимок уже прочитан)."""
    async with http_app(settings, router) as app:
        api = app.client
        cities = await api.get("/api/v1/cities", headers={"accept-language": "ru"})
        city_id = await _city_id(api, "novi-sad")
        districts = await api.get(f"/api/v1/cities/{city_id}/districts")
        engine = await app.container.get(AsyncEngine)
        with round_trips(engine) as trips:
            again = await api.get(
                "/api/v1/cities",
                headers={"accept-language": "ru", "if-none-match": cities.headers["etag"]},
            )
            same = await api.get(
                f"/api/v1/cities/{city_id}/districts",
                headers={"if-none-match": districts.headers["etag"]},
            )
            other = await api.get("/api/v1/cities", headers={"accept-language": "sr-Latn"})
        assert (again.status_code, same.status_code, other.status_code) == (304, 304, 200)
        assert other.headers["etag"] != cities.headers["etag"]
        assert trips.queries == 0


async def test_resolve_point_to_district(api: httpx.AsyncClient) -> None:
    response = await api.get(
        "/api/v1/geo/resolve", params=LIMAN_3, headers={"accept-language": "ru"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["district"]["slug"] == "liman-3"
    assert body["district"]["name"] == "Лиман 3"
    assert body["exact"] is True
    assert body["city_id"] == await _city_id(api, "novi-sad")


async def test_point_outside_service_area(api: httpx.AsyncClient) -> None:
    belgrade = await api.get("/api/v1/geo/resolve", params={"lat": 44.8125, "lon": 20.4573})
    assert belgrade.status_code == 404
    assert belgrade.json()["code"] == "outside_service_area"


@pytest.mark.parametrize("params", [{"lat": 91, "lon": 19}, {"lat": 45}, {"lat": "x", "lon": 19}])
async def test_resolve_validates_coordinates(
    api: httpx.AsyncClient, params: dict[str, str | int]
) -> None:
    assert (await api.get("/api/v1/geo/resolve", params=params)).status_code == 422


@pytest.mark.parametrize("city_id", ["0", "2147483648", "112528313883688129527808", "-1"])
async def test_city_id_out_of_int4_is_validation_error(
    api: httpx.AsyncClient, city_id: str
) -> None:
    response = await api.get(f"/api/v1/cities/{city_id}/districts")
    assert response.status_code == 422
