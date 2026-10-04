"""Прайс `/me/profile/services*` (DEVELOPMENT_PLAN 2.8b): CRUD, порядок, проверка при submit."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import accept_rules, insert_user

from app.modules.pricing.http.router import router as pricing
from app.modules.specialists.http.router import router as specialists
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    # кабинет `/me/profile` показывает фото профиля — ему нужен S3 (ссылки CDN, без запросов)
    async with http_app(storage_settings, specialists, pricing) as app:
        yield app


class Client:
    def __init__(self, app: HttpApp, headers: dict[str, str]) -> None:
        self.app, self.headers = app, headers

    async def post(self, path: str, **body: Any) -> httpx.Response:
        return await self.app.client.post(
            f"/api/v1{path}", json=body, headers=self.headers | {"idempotency-key": new_id().hex}
        )

    async def call(self, method: str, path: str, **body: Any) -> httpx.Response:
        return await self.app.client.request(
            method, f"/api/v1{path}", json=body or None, headers=self.headers
        )


@pytest.fixture
async def client(web: HttpApp, storage_settings: Settings) -> Client:
    async with web.container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session)
        await accept_rules(session, user_id)
    return Client(web, bearer(storage_settings, user_id))


async def scalar(client: Client, sql: str) -> int:
    engine = await client.app.container.get(AsyncEngine)
    async with engine.connect() as conn:
        return int((await conn.execute(text(sql))).scalar_one())


async def city(client: Client) -> int:
    return await scalar(client, "SELECT id FROM geo.cities WHERE slug = 'novi-sad'")


async def test_price_list_lives_in_the_profile(client: Client) -> None:
    missing = await client.post(
        "/me/profile/services", title="Розетка", price_type="fixed", price_min=100
    )
    assert (missing.status_code, missing.json()["code"]) == (409, "no_specialist_profile")


async def test_add_change_reorder_and_remove(client: Client) -> None:
    await client.post("/me/profile", kind="pro", city_id=await city(client))

    socket = await client.post(
        "/me/profile/services", title="Замена розетки", price_type="fixed", price_min=150_000
    )
    hour = await client.post(
        "/me/profile/services", title="Час работы", price_type="hourly", price_min=200_000
    )
    assert socket.status_code == 201, socket.text
    assert socket.json()["price_min"] == {"amount": 150_000, "currency": "RSD"}
    first, second = socket.json()["id"], hour.json()["id"]

    hidden = await client.call(
        "PATCH", f"/me/profile/services/{first}", is_active=False, description="С материалами"
    )
    order = await client.call("PUT", "/me/profile/services/order", service_ids=[second, first])
    listed = await client.call("GET", "/me/profile/services")

    assert hidden.json()["is_active"] is False
    assert [i["id"] for i in order.json()["items"]] == [second, first]
    assert [(i["title"], i["position"]) for i in listed.json()["items"]] == [
        ("Час работы", 0),
        ("Замена розетки", 1),
    ]
    assert (await client.call("DELETE", f"/me/profile/services/{second}")).status_code == 204
    after = await client.call("GET", "/me/profile/services")
    assert [(i["id"], i["position"]) for i in after.json()["items"]] == [(first, 0)]
    assert (await client.call("DELETE", f"/me/profile/services/{second}")).status_code == 404


@pytest.mark.authz
async def test_authz_foreign_service_cannot_be_changed_or_removed(
    client: Client, web: HttpApp, storage_settings: Settings
) -> None:
    """Чужой ресурс (8.4): у другого исполнителя (со своим профилем) чужой позиции нет."""
    await client.post("/me/profile", kind="pro", city_id=await city(client))
    created = await client.post(
        "/me/profile/services", title="Замена розетки", price_type="fixed", price_min=150_000
    )
    service = created.json()["id"]
    async with web.container() as request:
        session = await request.get(AsyncSession)
        other_id = await insert_user(session)
        await accept_rules(session, other_id)
    stranger = Client(web, bearer(storage_settings, other_id))
    await stranger.post("/me/profile", kind="pro", city_id=await city(stranger))

    changed = await stranger.call("PATCH", f"/me/profile/services/{service}", is_active=False)
    removed = await stranger.call("DELETE", f"/me/profile/services/{service}")

    assert changed.status_code == 404, changed.text
    assert removed.status_code == 404, removed.text
    listed = await client.call("GET", "/me/profile/services")
    assert [(i["id"], i["is_active"]) for i in listed.json()["items"]] == [(service, True)]


async def test_prices_are_validated(client: Client) -> None:
    await client.post("/me/profile", kind="pro", city_id=await city(client))

    no_price = await client.post("/me/profile/services", title="Розетка", price_type="fixed")
    bad_range = await client.post(
        "/me/profile/services", title="Покраска", price_type="range", price_min=5000, price_max=100
    )
    bad_order = await client.call("PUT", "/me/profile/services/order", service_ids=[str(new_id())])

    assert (no_price.status_code, no_price.json()["field"]) == (422, "price_min")
    assert (bad_range.status_code, bad_range.json()["field"]) == (422, "price_max")
    assert (bad_order.status_code, bad_order.json()["field"]) == (422, "service_ids")


async def test_specialist_without_prices_is_not_sent_to_review(client: Client) -> None:
    await client.post("/me/profile", kind="pro", city_id=await city(client))
    await client.call("PATCH", "/me/profile", headline="Электрик", work_modes=["at_own_place"])
    category = await scalar(
        client,
        "SELECT min(id) FROM catalog.categories WHERE is_active AND risk_level = 0"
        " AND parent_id IS NOT NULL",
    )
    await client.call("PUT", "/me/profile/categories", category_ids=[category])

    refused = await client.call("POST", "/me/profile/submit")
    await client.post(
        "/me/profile/services", title="Вызов мастера", price_type="from", price_min=100_000
    )
    accepted = await client.call("POST", "/me/profile/submit")

    assert (refused.status_code, refused.json()["missing"]) == (409, ["services"])
    assert accepted.json()["status"] == "pending_review"
