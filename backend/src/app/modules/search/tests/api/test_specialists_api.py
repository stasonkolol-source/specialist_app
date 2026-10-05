"""`GET /specialists` 🔓 (DEVELOPMENT_PLAN 4.2): выдача гостю, словарь категорий, опечатки,
пустая выдача, ошибки параметров и лимиты 60 / 120 в минуту. Данные коммитятся: у теста свой
город, после — строки удаляются.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.plugins.http import HttpApp, bearer, http_app

from app.modules.search.application.ports import SpecialistIndex
from app.modules.search.domain.index import IndexEntry
from app.modules.search.http.router import router as search_router
from app.modules.search.tests.builders import PLUMBER, entry
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CategoryId, CityId, new_id
from app.platform.settings import Settings

pytestmark = pytest.mark.integration

API = "/api/v1/specialists"


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    # свой адрес: лимит гостя считается по IP
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, search_router, client_ip=ip) as app:
        yield app


class Catalog:
    """Выдача одного города теста поверх настоящего словаря категорий (сиды каталога)."""

    def __init__(self, app: HttpApp) -> None:
        self.app = app
        self.city = CityId(950_000 + new_id().int % 40_000)

    async def scalar(self, sql: str, **params: object) -> Any:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()

    async def path(self, slug: str) -> tuple[CategoryId, ...]:
        path = await self.scalar("SELECT path FROM catalog.categories WHERE slug = :s", s=slug)
        return tuple(CategoryId(category) for category in path)

    async def add(self, *entries: IndexEntry) -> list[str]:
        async with self.app.container() as request:
            uow, index = await request.get(UnitOfWork), await request.get(SpecialistIndex)
            async with uow:
                await index.upsert(entries)
        return [str(item.profile_id) for item in entries]

    def specialist(self, name: str, **fields: Any) -> IndexEntry:
        return entry(name, city_id=self.city, **fields)

    async def get(self, headers: dict[str, str] | None = None, **params: Any) -> httpx.Response:
        return await self.app.client.get(
            API, params={"city_id": self.city, **params}, headers=headers
        )

    async def found(self, **params: Any) -> list[str]:
        response = await self.get(**params)
        assert response.status_code == 200, response.text
        return [item["profile_id"] for item in response.json()["items"]]

    async def clean(self) -> None:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.begin() as conn:
            for table in ("specialist_index", "query_log"):
                await conn.execute(
                    text(f"DELETE FROM search.{table} WHERE city_id = :c"), {"c": self.city}
                )


@pytest.fixture
async def catalog(web: HttpApp) -> AsyncIterator[Catalog]:
    catalog = Catalog(web)
    try:
        yield catalog
    finally:
        await catalog.clean()


async def test_guest_gets_ready_cards(catalog: Catalog) -> None:
    district = {"id": 7, "name": {"ru": "Лиман", "sr-Cyrl": "Лиман"}}
    [marko] = await catalog.add(
        catalog.specialist(
            "Marko Petrović",
            price_from=150_000,
            card={
                "display_name": "Marko Petrović",
                "kind": "pro",
                "district": district,
                "price_from_unit": "hour",
            },
        )
    )

    response = await catalog.get(headers={"accept-language": "sr-Latn"})

    assert response.status_code == 200
    assert response.headers["vary"] == "Accept-Language"
    assert response.headers["ratelimit-limit"] == "60"
    body = response.json()
    [card] = body["items"]
    assert (card["profile_id"], card["display_name"], card["price_from"]) == (
        marko,
        "Marko Petrović",
        150_000,
    )
    assert card["price_from_unit"] == "hour"
    assert card["district"] == {"id": 7, "name": "Liman"}
    assert (card["is_new"], card["rating"], card["avatar"], card["distance_m"]) == (
        True,
        None,
        None,
        None,
    )
    assert (body["next_cursor"], body["hints"], body["did_you_mean"]) == (None, [], None)


@pytest.mark.parametrize("q", ["электрик", "električar", "Електричар", "elektricar"])
async def test_category_word_in_any_script_gives_one_result(catalog: Catalog, q: str) -> None:
    electrical, plumbing = await catalog.path("electrical"), await catalog.path("plumbing")
    [electrician, _] = await catalog.add(
        catalog.specialist("A", category_ids=electrical),
        catalog.specialist("B", category_ids=plumbing, document=PLUMBER),
    )

    response = await catalog.get(q=q)

    body = response.json()
    assert [item["profile_id"] for item in body["items"]] == [electrician]
    assert electrical[-1] in body["category_ids"]


async def test_typo_gets_a_suggestion_and_its_results(catalog: Catalog) -> None:
    electrical = await catalog.path("electrical")
    [electrician] = await catalog.add(catalog.specialist("A", category_ids=electrical))

    body = (await catalog.get(q="elektricr")).json()

    assert [item["profile_id"] for item in body["items"]] == [electrician]
    assert body["did_you_mean"] is not None


async def test_nothing_found_is_logged_with_hints(catalog: Catalog) -> None:
    await catalog.add(catalog.specialist("A"))

    body = (await catalog.get(q="qwertyzzz", available_today="true")).json()

    assert (body["items"], body["hints"]) == ([], ["relax_filters", "post_job"])
    logged = await catalog.scalar(
        "SELECT q || ':' || array_to_string(filters, ',') FROM search.query_log WHERE city_id = :c",
        c=catalog.city,
    )
    assert logged == "qwertyzzz:available_today"


async def test_control_characters_do_not_break_search(catalog: Catalog) -> None:
    await catalog.add(catalog.specialist("A"))

    response = await catalog.get(q="elek\x00trik")  # NUL PostgreSQL не примет вовсе

    assert response.status_code == 200


async def test_casual_only_on_request(catalog: Catalog) -> None:
    pro, casual = await catalog.add(
        catalog.specialist("Pro"), catalog.specialist("Casual", kind="casual")
    )

    assert await catalog.found() == [pro]
    assert await catalog.found(kind="casual") == [casual]


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"lat": 45.25}, "validation_failed"),
        ({"sort": "distance"}, "validation_failed"),
        ({"radius_km": 3}, "validation_failed"),
        ({"cursor": "garbage!"}, "invalid_cursor"),
        ({"kind": "boss"}, None),
        ({"city_id": None}, None),
    ],
)
async def test_bad_parameters_are_422(
    catalog: Catalog, params: dict[str, Any], code: str | None
) -> None:
    query = {"city_id": catalog.city, **params}
    response = await catalog.app.client.get(
        API, params={key: value for key, value in query.items() if value is not None}
    )

    assert response.status_code == 422, response.text
    if code is not None:
        assert response.json()["code"] == code


async def test_guest_limit_is_per_address_and_signed_in_has_its_own(
    catalog: Catalog, storage_settings: Settings
) -> None:
    for _ in range(60):
        assert (await catalog.get()).status_code == 200

    blocked = await catalog.get()
    signed_in = await catalog.get(headers=bearer(storage_settings))

    assert blocked.status_code == 429
    assert (signed_in.status_code, signed_in.headers["ratelimit-limit"]) == (200, "120")


async def test_paging_walks_the_whole_list(catalog: Catalog) -> None:
    added = set(await catalog.add(*(catalog.specialist(f"M{number}") for number in range(5))))

    first = (await catalog.get(limit=2)).json()
    seen = [item["profile_id"] for item in first["items"]]
    cursor = first["next_cursor"]
    while cursor is not None:
        page = (await catalog.get(limit=2, cursor=cursor)).json()
        seen += [item["profile_id"] for item in page["items"]]
        cursor = page["next_cursor"]

    assert len(seen) == len(set(seen)) == 5
    assert set(seen) == added
    assert all(UUID(profile_id) for profile_id in seen)


async def test_count_matches_the_list(catalog: Catalog) -> None:
    electrical, plumbing = await catalog.path("electrical"), await catalog.path("plumbing")
    await catalog.add(
        catalog.specialist("A", category_ids=electrical),
        catalog.specialist("B", category_ids=electrical, languages=("sr",)),
        catalog.specialist("C", category_ids=plumbing, document=PLUMBER),
    )

    for params in ({}, {"q": "električar"}, {"languages": "sr"}, {"q": "qwertyzzz"}):
        counted = (
            await catalog.app.client.get(f"{API}/count", params={"city_id": catalog.city, **params})
        ).json()
        assert counted == {"count": len(await catalog.found(**params)), "capped": False}, params


async def test_counts_by_category_include_subcategories(catalog: Catalog) -> None:
    electrical, plumbing = await catalog.path("electrical"), await catalog.path("plumbing")
    await catalog.add(
        catalog.specialist("A", category_ids=electrical),
        catalog.specialist("B", category_ids=electrical),
        catalog.specialist("C", category_ids=plumbing, document=PLUMBER),
        catalog.specialist("Casual", category_ids=electrical, kind="casual"),
    )

    response = await catalog.app.client.get(f"{API}/by-category", params={"city_id": catalog.city})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=300"
    counts = {item["category_id"]: item["count"] for item in response.json()["items"]}
    assert counts[electrical[-1]] == 2
    assert counts[plumbing[-1]] == 1
    assert counts[electrical[0]] == 3  # раздел — со всеми подкатегориями
