"""`GET /suggest` 🔓 (DEVELOPMENT_PLAN 4.3a): подсказки по настоящему словарю категорий."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.plugins.http import HttpApp, http_app

from app.modules.search.http.router import router as search_router
from app.platform.cache.port import JsonCache
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings

pytestmark = pytest.mark.integration

API = "/api/v1/suggest"


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, search_router, client_ip=ip) as app:
        yield app


async def category(app: HttpApp, slug: str) -> int:
    engine = await app.container.get(AsyncEngine)
    async with engine.connect() as conn:
        found = await conn.execute(
            text("SELECT id FROM catalog.categories WHERE slug = :s"), {"s": slug}
        )
        return int(found.scalar_one())


@pytest.mark.parametrize(
    ("typed", "language", "name"),
    [
        ("elek", "sr-Latn", "Električar"),
        ("элек", "ru", "Электрик"),
        ("елек", "sr-Cyrl", "Електричар"),
    ],
)
async def test_word_start_in_three_scripts(
    web: HttpApp, typed: str, language: str, name: str
) -> None:
    electrical = await category(web, "electrical")

    response = await web.client.get(API, params={"q": typed}, headers={"accept-language": language})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=300"
    items = response.json()["items"]
    assert len({item["category_id"] for item in items}) == len(items) <= 8
    [ours] = [item for item in items if item["category_id"] == electrical]
    assert (ours["name"], ours["fuzzy"]) == (name, False)


async def test_typo_is_suggested_by_similarity(web: HttpApp) -> None:
    plumbing = await category(web, "plumbing")

    items = (await web.client.get(API, params={"q": "vodoinstaltr"})).json()["items"]

    assert [item["fuzzy"] for item in items if item["category_id"] == plumbing] == [True]


async def test_answer_stays_in_the_cache(web: HttpApp) -> None:
    typed = "santeh"

    await web.client.get(API, params={"q": typed})

    cached = await (await web.container.get(JsonCache)).get(f"search.suggest:v1:{typed}")
    assert isinstance(cached, list)
    assert cached


@pytest.mark.parametrize(("q", "status"), [("e", 200), ("\x00", 200), ("", 422), ("x" * 65, 422)])
async def test_input_length(web: HttpApp, q: str, status: int) -> None:
    response = await web.client.get(API, params={"q": q})

    assert response.status_code == status
    if status == 200:
        assert response.json() == {"items": []}
