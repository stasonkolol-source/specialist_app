"""API-тесты identity: приложение целиком на PostgreSQL и Valkey из testcontainers.

Данные коммитятся, поэтому у каждого теста свои Telegram id и IP (лимиты /auth/*).
"""

from collections.abc import AsyncIterator, Callable
from datetime import datetime

import httpx
import pytest
from tests.plugins.http import http_client
from tests.plugins.identity import bearer as bearer
from tests.plugins.identity import login as login
from tests.plugins.identity import new_telegram_id, signed_init_data

from app.modules.identity.http.router import router
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings

InitData = Callable[..., str]


@pytest.fixture
def telegram_id() -> int:
    return new_telegram_id()


@pytest.fixture
def init_data(settings: Settings, telegram_id: int) -> InitData:
    def build(
        *, auth_date: datetime | None = None, start_param: str | None = None, **user: object
    ) -> str:
        return signed_init_data(
            settings, telegram_id, auth_date=auth_date, start_param=start_param, **user
        )

    return build


@pytest.fixture
async def api(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_client(settings, router, client_ip=ip) as client:
        yield client
