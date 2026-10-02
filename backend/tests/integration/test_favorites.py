"""Избранное (DEVELOPMENT_PLAN 4.6) через API: сохранить видимого специалиста, список S12 — новые
первыми и только видимые, убрать, повтор без ошибки, гостю — 401. Данные коммитятся.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.entrypoints._wiring import module_routers
from app.modules.specialists.application.use_cases.hide_profile import (
    HideProfile,
    HideProfileCommand,
)
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import insert_user
from tests.plugins.search import Specialist

pytestmark = pytest.mark.integration

API = "/api/v1/me/favorites"


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield app


async def listed(app: HttpApp) -> Specialist:
    """Опубликованный специалист, уже в read-model каталога."""
    specialist = Specialist(app.container)
    await specialist.publish()
    await specialist.handle("search.on_profile_published")
    return specialist


class Client:
    def __init__(self, app: HttpApp, settings: Settings, user_id: UserId) -> None:
        self.app, self.headers = app, bearer(settings, user_id)

    async def save(self, profile_id: object) -> httpx.Response:
        return await self.app.client.put(f"{API}/profile/{profile_id}", headers=self.headers)

    async def drop(self, profile_id: object) -> httpx.Response:
        return await self.app.client.delete(f"{API}/profile/{profile_id}", headers=self.headers)

    async def names(self) -> list[str]:
        response = await self.app.client.get(API, headers=self.headers)
        assert response.status_code == 200, response.text
        return [item["display_name"] for item in response.json()["items"]]

    async def ids(self) -> list[str]:
        response = await self.app.client.get(API, headers=self.headers)
        return [item["profile_id"] for item in response.json()["items"]]


async def client(app: HttpApp, settings: Settings) -> Client:
    async with app.container() as request:
        user_id = await insert_user(await request.get(AsyncSession))
    return Client(app, settings, user_id)


async def test_saved_specialists_are_listed_newest_first(
    web: HttpApp, storage_settings: Settings
) -> None:
    first, second = await listed(web), await listed(web)
    me = await client(web, storage_settings)

    assert (await me.save(first.profile_id)).status_code == 204
    assert (await me.save(second.profile_id)).status_code == 204
    assert (await me.save(first.profile_id)).status_code == 204

    assert await me.ids() == [str(second.profile_id), str(first.profile_id)]
    assert (await me.drop(second.profile_id)).status_code == 204
    assert (await me.drop(second.profile_id)).status_code == 204
    assert await me.ids() == [str(first.profile_id)]


async def test_hidden_specialist_cannot_be_saved_and_drops_out(
    web: HttpApp, storage_settings: Settings
) -> None:
    specialist = await listed(web)
    me = await client(web, storage_settings)
    assert (await me.save(specialist.profile_id)).status_code == 204

    await specialist.call(HideProfile, HideProfileCommand(actor_id=specialist.user_id))
    await specialist.handle("search.on_profile_hidden")

    assert await me.ids() == []
    unknown = await me.save(new_id())
    assert (unknown.status_code, unknown.json()["code"]) == (404, "not_found")


async def test_favorites_need_sign_in(web: HttpApp) -> None:
    assert (await web.client.get(API)).status_code == 401
    assert (await web.client.put(f"{API}/profile/{new_id()}")).status_code == 401
