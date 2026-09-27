"""Атрибуция через вход Mini App (DEVELOPMENT_PLAN 1.4b): startapp → UserRegistered → growth.

Приложение целиком на PostgreSQL и Valkey из testcontainers. Подписчик выполняется
обёрткой воркера (tests/plugins/queue.py): так проходит весь путь события, как на стенде.
"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.plugins.http import HttpApp, http_app
from tests.plugins.identity import login, new_telegram_id, signed_init_data, user_id_of
from tests.plugins.queue import run_queued

from app.modules.growth.application.ports import RECORD_ATTRIBUTION
from app.modules.identity.http.router import router as identity_router
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings

pytestmark = pytest.mark.integration

SHARED_JOB = "j_02y9UKmeRG6vSNbdsEYkkR_rAB12CD"


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(settings, identity_router, client_ip=ip) as app:
        yield app


async def attribution(app: HttpApp, user_id: UserId) -> dict[str, object] | None:
    async with app.container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT source, start_param, referral_code, entry_point"
                    " FROM growth.attributions WHERE user_id = :user_id"
                ),
                {"user_id": user_id},
            )
        ).one_or_none()
        return dict(row._mapping) if row is not None else None


async def test_attribution_is_written_once(app: HttpApp, settings: Settings) -> None:
    telegram_id = new_telegram_id()
    tokens = await login(
        app.client, signed_init_data(settings, telegram_id, start_param=SHARED_JOB)
    )
    user_id = user_id_of(tokens)

    assert await run_queued(app.container, RECORD_ATTRIBUTION, user_id=user_id) == 1
    expected = {
        "source": "job",
        "start_param": SHARED_JOB,
        "referral_code": "AB12CD",
        "entry_point": "mini_app",
    }
    assert await attribution(app, user_id) == expected

    # второе касание: вход по другой ссылке — атрибуция та же
    await login(app.client, signed_init_data(settings, telegram_id, start_param="h_rCHAN1"))
    assert await run_queued(app.container, RECORD_ATTRIBUTION, user_id=user_id) == 0
    assert await attribution(app, user_id) == expected


async def test_registration_without_startapp_is_organic(app: HttpApp, settings: Settings) -> None:
    tokens = await login(app.client, signed_init_data(settings, new_telegram_id()))
    user_id = user_id_of(tokens)

    assert await run_queued(app.container, RECORD_ATTRIBUTION, user_id=user_id) == 1
    assert await attribution(app, user_id) == {
        "source": "organic",
        "start_param": None,
        "referral_code": None,
        "entry_point": "mini_app",
    }


async def test_unknown_startapp_is_kept_as_unknown(app: HttpApp, settings: Settings) -> None:
    tokens = await login(
        app.client, signed_init_data(settings, new_telegram_id(), start_param="promo-2026")
    )
    user_id = user_id_of(tokens)

    await run_queued(app.container, RECORD_ATTRIBUTION, user_id=user_id)
    found = await attribution(app, user_id)
    assert found is not None
    assert (found["source"], found["start_param"]) == ("unknown", "promo-2026")
