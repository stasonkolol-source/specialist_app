"""POST /me/telegram/write-access (DEVELOPMENT_PLAN 1.4b, ARCHITECTURE §8.5, §11.1).

Приложение целиком на PostgreSQL и Valkey из testcontainers: вход — как у Mini App
(POST /auth/telegram), данные коммитятся, поэтому у каждого теста свой Telegram id и IP.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.plugins.http import HttpApp, http_app
from tests.plugins.identity import bearer, login, new_telegram_id, signed_init_data, user_id_of

from app.modules.identity.http.router import router as identity_router
from app.modules.notifications.http.router import router
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings

pytestmark = pytest.mark.integration

WRITE_ACCESS = "/api/v1/me/telegram/write-access"


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(settings, identity_router, router, client_ip=ip) as app:
        yield app


async def channels(app: HttpApp, user_id: UserId) -> list[dict[str, object]]:
    async with app.container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT kind, address, granted_via FROM notifications.channels"
                " WHERE user_id = :user_id"
            ),
            {"user_id": user_id},
        )
        return [dict(row._mapping) for row in rows]


async def test_write_access_is_saved_and_idempotent(app: HttpApp, settings: Settings) -> None:
    telegram_id = new_telegram_id()
    tokens = await login(app.client, signed_init_data(settings, telegram_id))

    first = await app.client.post(WRITE_ACCESS, headers=bearer(tokens))
    again = await app.client.post(WRITE_ACCESS, headers=bearer(tokens))

    assert first.status_code == 200, first.text
    body = first.json()
    assert (body["writable"], body["granted_via"]) == (True, "mini_app")
    assert again.status_code == 200
    assert again.json() == body
    assert await channels(app, user_id_of(tokens)) == [
        {"kind": "telegram", "address": str(telegram_id), "granted_via": "mini_app"}
    ]


async def test_write_access_needs_session(app: HttpApp) -> None:
    response = await app.client.post(WRITE_ACCESS)
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "not_authenticated"


async def test_write_access_ignores_body(app: HttpApp, settings: Settings) -> None:
    """Состояние задаёт только сервер: поле в теле не превращает канал в выключенный."""
    tokens = await login(app.client, signed_init_data(settings, new_telegram_id()))
    response = await app.client.post(WRITE_ACCESS, headers=bearer(tokens), json={"writable": False})
    assert response.status_code == 200
    assert response.json()["writable"] is True
