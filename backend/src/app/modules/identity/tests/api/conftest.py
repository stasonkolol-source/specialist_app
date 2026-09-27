"""API-тесты identity: приложение целиком на PostgreSQL и Valkey из testcontainers.

Данные коммитятся, поэтому у каждого теста свои Telegram id и IP (лимиты /auth/*).
"""

import json
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from urllib.parse import urlencode

import httpx
import pytest
from tests.plugins.http import http_client

from app.modules.identity.http.router import router
from app.platform.kernel.clock import SystemClock
from app.platform.kernel.ids import new_id
from app.platform.security.initdata import sign
from app.platform.settings import Settings

InitData = Callable[..., str]


@pytest.fixture
def telegram_id() -> int:
    return 500_000_000 + new_id().int % 100_000_000


@pytest.fixture
def init_data(settings: Settings, telegram_id: int) -> InitData:
    def build(*, auth_date: datetime | None = None, **user: object) -> str:
        profile = {"id": telegram_id, "first_name": "Ana", "language_code": "sr"} | user
        fields = {
            "auth_date": str(int((auth_date or SystemClock().now()).timestamp())),
            "user": json.dumps(profile, separators=(",", ":"), ensure_ascii=False),
        }
        return urlencode(
            fields | {"hash": sign(fields, settings.telegram.bot_token.get_secret_value())}
        )

    return build


@pytest.fixture
async def api(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_client(settings, router, client_ip=ip) as client:
        yield client


async def login(api: httpx.AsyncClient, init_data: str) -> dict[str, object]:
    response = await api.post(
        "/api/v1/auth/telegram", headers={"authorization": f"tma {init_data}"}
    )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def bearer(tokens: dict[str, object]) -> dict[str, str]:
    return {"authorization": f"Bearer {tokens['access_token']}"}
