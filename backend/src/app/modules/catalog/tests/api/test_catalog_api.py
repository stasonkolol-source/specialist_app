"""GET /categories 🔓 (DEVELOPMENT_PLAN 1.3b): дерево на трёх языках, ETag → 304, ориентиры цен."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from tests.plugins.http import http_client

from app.modules.catalog.http.router import router
from app.platform.settings import Settings

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("catalog_seeded")]

ROOTS = ["handyman", "beauty", "cleaning", "moving", "lessons"]


@pytest.fixture
async def api(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with http_client(settings, router) as client:
        yield client


def _by_slug(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for node in nodes:
        found[node["slug"]] = node
        found |= _by_slug(node["children"])
    return found


@pytest.mark.parametrize(
    ("language", "handyman", "electrical", "chandeliers"),
    [
        ("ru", "Мастер на час", "Электрик", "Люстры и светильники"),
        ("sr-Latn", "Majstor za kućne popravke", "Električar", "Lusteri i svetiljke"),
        ("sr-Cyrl", "Мајстор за кућне поправке", "Електричар", "Лустери и светиљке"),
    ],
)
async def test_tree_is_localized(
    api: httpx.AsyncClient, language: str, handyman: str, electrical: str, chandeliers: str
) -> None:
    response = await api.get("/api/v1/categories", headers={"accept-language": language})
    assert response.status_code == 200
    tree = response.json()
    assert [root["slug"] for root in tree] == ROOTS
    nodes = _by_slug(tree)
    assert nodes["handyman"]["name"] == handyman
    assert nodes["handyman"]["icon"] == "wrench"
    assert [c["slug"] for c in nodes["handyman"]["children"]] == [
        "small-repairs",
        "furniture-assembly",
        "plumbing",
        "electrical",
    ]
    assert nodes["electrical"]["name"] == electrical
    assert nodes["electrical"]["tags"][0] == {
        "id": nodes["electrical"]["tags"][0]["id"],
        "slug": "chandeliers",
        "name": chandeliers,
    }
    assert len(nodes) == 18


async def test_moderation_settings_are_not_exposed(api: httpx.AsyncClient) -> None:
    electrical = _by_slug((await api.get("/api/v1/categories")).json())["electrical"]
    assert set(electrical) == {"id", "slug", "name", "icon", "price_hint", "tags", "children"}


async def test_etag_and_if_none_match(api: httpx.AsyncClient) -> None:
    first = await api.get("/api/v1/categories", headers={"accept-language": "ru"})
    etag = first.headers["etag"]
    assert etag.startswith('"')
    assert first.headers["cache-control"] == ("public, max-age=300, stale-while-revalidate=86400")
    assert first.headers["vary"] == "Accept-Language"

    for header in (etag, f"W/{etag}", f'"other", {etag}', "*"):
        cached = await api.get(
            "/api/v1/categories", headers={"accept-language": "ru", "if-none-match": header}
        )
        assert cached.status_code == 304, header
        assert cached.content == b""
        assert cached.headers["etag"] == etag

    serbian = await api.get(
        "/api/v1/categories", headers={"accept-language": "sr-Latn", "if-none-match": etag}
    )
    assert serbian.status_code == 200
    assert serbian.headers["etag"] != etag
    stale = await api.get(
        "/api/v1/categories", headers={"accept-language": "ru", "if-none-match": '"stale"'}
    )
    assert stale.status_code == 200
    assert stale.json() == first.json()


async def test_price_hints_for_city_in_para(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/v1/categories", params={"city": "novi-sad"})
    nodes = _by_slug(response.json())
    assert nodes["electrical"]["price_hint"] == {
        "min": {"amount": 100_000, "currency": "RSD"},
        "max": {"amount": 400_000, "currency": "RSD"},
        "unit": "item",
    }
    assert nodes["handyman"]["price_hint"] is None
    no_city = _by_slug((await api.get("/api/v1/categories")).json())
    assert no_city["electrical"]["price_hint"] is None
    elsewhere = await api.get("/api/v1/categories", params={"city": "beograd"})
    assert elsewhere.status_code == 200
    assert _by_slug(elsewhere.json())["electrical"]["price_hint"] is None
    assert response.headers["etag"] != elsewhere.headers["etag"]


@pytest.mark.parametrize("city", ["Novi Sad", "novi_sad", "-novi", "x" * 65, ""])
async def test_city_must_be_a_slug(api: httpx.AsyncClient, city: str) -> None:
    response = await api.get("/api/v1/categories", params={"city": city})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
