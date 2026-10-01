"""API-тесты кабинета исполнителя: приложение целиком на PostgreSQL из testcontainers.

Данные коммитятся — у каждого теста свой пользователь. Справочники — сиды пилотной зоны
(Нови-Сад, категории), их грузят фикстуры `geo_seeded` и `catalog_seeded`.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import accept_rules, insert_user

from app.modules.specialists.http.router import router
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings


@dataclass
class Cabinet:
    """Кабинет от имени пользователя."""

    app: HttpApp
    user_id: UserId
    headers: dict[str, str]

    async def create(self, **body: Any) -> httpx.Response:
        payload = {"kind": "pro", "city_id": await self.city_id()} | body
        return await self.app.client.post(
            "/api/v1/me/profile",
            json=payload,
            headers=self.headers | {"idempotency-key": f"k-{new_id().hex}"},
        )

    async def get(self) -> httpx.Response:
        return await self.app.client.get("/api/v1/me/profile", headers=self.headers)

    async def call(
        self, method: str, path: str = "", *, version: int | None = None, **body: Any
    ) -> httpx.Response:
        headers = self.headers | ({"if-match": f'"{version}"'} if version is not None else {})
        return await self.app.client.request(
            method, f"/api/v1/me/profile{path}", json=body or None, headers=headers
        )

    async def scalar(self, sql: str, **params: object) -> Any:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()

    async def city_id(self) -> int:
        return int(await self.scalar("SELECT id FROM geo.cities WHERE slug = 'novi-sad'"))

    async def districts(self, count: int = 2) -> list[int]:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT d.id FROM geo.districts d JOIN geo.cities c ON c.id = d.city_id"
                    " WHERE c.slug = 'novi-sad' ORDER BY d.id LIMIT :n"
                ),
                {"n": count},
            )
            return [int(r[0]) for r in rows]

    async def category(self) -> int:
        return int(
            await self.scalar(
                "SELECT id FROM catalog.categories WHERE is_active AND risk_level = 0"
                " AND parent_id IS NOT NULL ORDER BY id LIMIT 1"
            )
        )


@pytest.fixture
async def web(settings: Settings, geo_seeded: None, catalog_seeded: None) -> AsyncIterator[HttpApp]:
    async with http_app(settings, router) as app:
        yield app


async def cabinet_for(app: HttpApp, settings: Settings, *, rules: bool = True) -> Cabinet:
    async with app.container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session)
        if rules:
            await accept_rules(session, user_id)
    return Cabinet(app=app, user_id=user_id, headers=bearer(settings, user_id))


@pytest.fixture
async def cabinet(web: HttpApp, settings: Settings) -> Cabinet:
    return await cabinet_for(web, settings)
