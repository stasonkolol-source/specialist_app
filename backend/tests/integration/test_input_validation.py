"""Неверный ввод — 422, а не 500 (QA ADV-01, ADV-02, ADV-03, ADV-04, ADV-05): запросы из находок
против настоящей базы.

- Числа за границей колонки (2^31 в id справочника, 10^20 в сумме) — 422 `validation_error`,
  в том числе у гостя на ленте и каталоге.
- Позиция прайса с несуществующей категорией — 422 `invalid_service` (был внешний ключ и 500).
- NUL в тексте вычищается, текст из одних невидимых символов — 422; языки заявки — из перечня.
"""

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import module_routers
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import accept_rules, insert_user

pytestmark = pytest.mark.integration

API = "/api/v1"
INT4_OVER = 2**31
HUGE = (2**31, 2**63, 10**30)
INVISIBLE = "\u200b\u2060\ufeff\u200b\u2060\ufeff"


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield app


class User:
    def __init__(self, app: HttpApp, headers: dict[str, str]) -> None:
        self.app, self.headers = app, headers

    async def call(self, method: str, path: str, body: Any = None) -> httpx.Response:
        headers = self.headers | {"Idempotency-Key": new_id().hex}
        return await self.app.client.request(method, f"{API}{path}", json=body, headers=headers)


@pytest.fixture
async def user(web: HttpApp, storage_settings: Settings) -> User:
    async with web.container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session)
        await accept_rules(session, user_id)
    return User(web, bearer(storage_settings, user_id))


async def scalar(app: HttpApp, sql: str) -> Any:
    engine = await app.container.get(AsyncEngine)
    async with engine.connect() as conn:
        return (await conn.execute(text(sql))).scalar()


async def job_body(app: HttpApp) -> dict[str, Any]:
    mark = "".join(chr(ord("a") + int(digit, 16)) for digit in new_id().hex[-12:])
    return {
        "title": f"Повесить полку {mark}",
        "description": f"Полка над столом, стена бетон. Метка {mark}.",
        "category_id": await scalar(
            app,
            "SELECT min(id) FROM catalog.categories WHERE is_active AND jobs_enabled"
            " AND risk_level = 0 AND parent_id IS NOT NULL",
        ),
        "urgency": "this_week",
        "budget_type": "negotiable",
        "city_id": await scalar(app, "SELECT id FROM geo.cities WHERE slug = 'novi-sad'"),
    }


def assert_invalid(response: httpx.Response, code: str = "validation_error") -> None:
    assert (response.status_code, response.json()["code"]) == (422, code), response.text


@pytest.mark.parametrize(
    "query",
    [
        f"/jobs?city_id={INT4_OVER}",
        f"/jobs?city_id=1&category={INT4_OVER}",
        f"/jobs?city_id=1&district={INT4_OVER}",
        "/jobs?city_id=1&budget_from=100000000000000000000",
        f"/jobs/count?city_id={INT4_OVER}",
        f"/specialists?city_id={INT4_OVER}",
        f"/specialists?city_id=1&category_id={INT4_OVER}",
        f"/specialists?city_id=1&district_ids={INT4_OVER}",
        "/specialists?city_id=1&price_max=100000000000000000000",
        f"/specialists/count?city_id={INT4_OVER}",
        f"/specialists/by-category?city_id={INT4_OVER}",
        # NUL и мусор в языковом фильтре — тоже не до базы
        "/jobs?city_id=1&lang=%00",
        "/jobs/count?city_id=1&lang=xx-evil",
        "/specialists?city_id=1&languages=%00",
        "/specialists/count?city_id=1&languages=xx-evil",
    ],
)
async def test_guest_out_of_range_numbers_are_422(web: HttpApp, query: str) -> None:
    assert_invalid(await web.client.get(f"{API}{query}"))


async def test_out_of_range_ids_in_bodies_are_422(web: HttpApp, user: User) -> None:
    body = await job_body(web)
    city = body["city_id"]
    for value in HUGE:
        for field in ("category_id", "city_id", "district_id"):
            assert_invalid(await user.call("POST", "/jobs", {**body, field: value}))
        criteria = {"category_ids": [body["category_id"]], "city_id": city}
        for override in (
            {"category_ids": [value]},
            {"city_id": value},
            {"district_ids": [value]},
        ):
            alert = {"criteria": {**criteria, **override}}
            assert_invalid(await user.call("POST", "/me/job-alerts", alert))
    profile = await user.call("POST", "/me/profile", {"kind": "pro", "city_id": city})
    assert profile.status_code == 201, profile.text
    categories = {"category_ids": [INT4_OVER]}
    assert_invalid(await user.call("PUT", "/me/profile/categories", categories))
    assert_invalid(await user.call("PUT", "/me/profile/areas", {"district_ids": [INT4_OVER]}))


async def test_price_item_with_unknown_category_is_422(web: HttpApp, user: User) -> None:
    city = await scalar(web, "SELECT id FROM geo.cities WHERE slug = 'novi-sad'")
    profile = await user.call("POST", "/me/profile", {"kind": "pro", "city_id": city})
    assert profile.status_code == 201, profile.text
    item = {"title": "[QA] svc cat", "price_type": "fixed", "price_min": 100}
    for category in (9999, 999_999, 2**31 - 1):
        added = await user.call("POST", "/me/profile/services", {**item, "category_id": category})
        assert_invalid(added, "invalid_service")
    root = await scalar(web, "SELECT min(id) FROM catalog.categories WHERE parent_id IS NULL")
    created = await user.call("POST", "/me/profile/services", {**item, "category_id": root})
    assert created.status_code == 201, created.text
    changed = await user.call(
        "PATCH", f"/me/profile/services/{created.json()['id']}", {"category_id": 9999}
    )
    assert_invalid(changed, "invalid_service")


async def test_nul_is_stripped_and_invisible_text_is_rejected(web: HttpApp, user: User) -> None:
    template = await user.call(
        "POST",
        "/me/response-templates",
        {
            "title": "[QA] a\u0000b",
            "message": "[QA] a\u0000b",
            "availability_note": "[QA] a\u0000b",
            "price_type": "negotiable",
        },
    )
    assert template.status_code == 201, template.text
    assert (template.json()["title"], template.json()["message"]) == ("[QA] ab", "[QA] ab")
    body = await job_body(web)
    assert_invalid(await user.call("POST", "/jobs", {**body, "title": INVISIBLE}))
    created = await user.call("POST", "/jobs", {**body, "title": f"{body['title']}\u0000"})
    assert created.status_code == 201, created.text
    assert created.json()["title"] == body["title"]


async def test_job_languages_are_the_supported_codes(web: HttpApp, user: User) -> None:
    body = await job_body(web)
    for junk in (["xx-evil", "<script>", "ru", "ru"], ["a" * 5000]):
        assert_invalid(await user.call("POST", "/jobs", {**body, "languages": junk}))
    created = await user.call("POST", "/jobs", {**body, "languages": ["ru", "sr"]})
    assert created.status_code == 201, created.text
    assert created.json()["languages"] == ["ru", "sr"]
