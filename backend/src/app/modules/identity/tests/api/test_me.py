"""GET и PATCH /me (DEVELOPMENT_PLAN 0.15b), POST /me/phone — бейдж «Телефон подтверждён»."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.plugins.http import http_client
from tests.plugins.identity import (
    new_phone,
    new_telegram_id,
    phone_verification,
    signed_contact,
    signed_init_data,
)

from app.modules.identity.http.router import router
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings

from .conftest import InitData, bearer, login

pytestmark = pytest.mark.integration


async def test_me_returns_user_with_etag(api: httpx.AsyncClient, init_data: InitData) -> None:
    tokens = await login(api, init_data(first_name="Иван", language_code="ru"))
    response = await api.get("/api/v1/me", headers=bearer(tokens))
    assert response.status_code == 200
    assert response.headers["etag"] == '"1"'
    assert response.json()["display_name"] == "Иван"
    assert response.json()["ui_locale"] == "ru"


async def test_patch_me_updates_name_and_locale(
    api: httpx.AsyncClient, init_data: InitData
) -> None:
    tokens = await login(api, init_data())
    etag = (await api.get("/api/v1/me", headers=bearer(tokens))).headers["etag"]
    response = await api.patch(
        "/api/v1/me",
        headers=bearer(tokens) | {"if-match": etag},
        json={"display_name": "  Ана  Петровић ", "ui_locale": "sr-Cyrl"},
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == "Ана Петровић"
    assert response.json()["ui_locale"] == "sr-Cyrl"
    assert response.headers["etag"] != etag

    stale = await api.patch(
        "/api/v1/me", headers=bearer(tokens) | {"if-match": etag}, json={"display_name": "X"}
    )
    assert stale.status_code == 412
    assert stale.json()["code"] == "stale_version"


@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        ({"display_name": ""}, "display_name", "string_too_short"),
        ({"display_name": "x" * 65}, "display_name", "string_too_long"),
        ({"ui_locale": "de"}, "ui_locale", "enum"),
    ],
)
async def test_patch_me_validation(
    api: httpx.AsyncClient, init_data: InitData, body: dict[str, str], field: str, code: str
) -> None:
    tokens = await login(api, init_data())
    response = await api.patch("/api/v1/me", headers=bearer(tokens), json=body)
    assert response.status_code == 422
    [error] = response.json()["errors"]
    assert (error["field"], error["code"]) == (field, code)


async def test_invisible_name_is_rejected_by_domain(
    api: httpx.AsyncClient, init_data: InitData
) -> None:
    tokens = await login(api, init_data())
    response = await api.patch(
        "/api/v1/me", headers=bearer(tokens), json={"display_name": "\u200b \u200b"}
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_display_name"


async def test_phone_verification_gives_the_badge_without_the_number(
    api: httpx.AsyncClient,
    init_data: InitData,
    settings: Settings,
    telegram_id: int,
    migrator_engine: AsyncEngine,
) -> None:
    """POST /me/phone (S33, S32c, S43): флаг выключен (до редакции 2 политики) — 404 и ничего не
    пишется; включён — подписанный контакт → бейдж и уровень 1, номера в ответе нет. Тот же номер
    у другого аккаунта — 409, чужой контакт — 422."""
    tokens = await login(api, init_data())
    phone = new_phone()
    contact = {"contact": signed_contact(settings, telegram_id, phone)}

    off = await api.post("/api/v1/me/phone", headers=bearer(tokens), json=contact)
    assert (off.status_code, off.json()["code"]) == (404, "phone_verification_unavailable")
    assert (await api.get("/api/v1/me", headers=bearer(tokens))).json()["phone_verified"] is False

    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"  # лимиты /auth
    async with (
        phone_verification(migrator_engine),
        http_client(settings, router, client_ip=ip) as on,
    ):
        response = await on.post("/api/v1/me/phone", headers=bearer(tokens), json=contact)

        assert response.status_code == 200, response.text
        assert (response.json()["phone_verified"], response.json()["trust_level"]) == (True, 1)
        assert phone.removeprefix("+") not in response.text
        me = await on.get("/api/v1/me", headers=bearer(tokens))
        assert phone.removeprefix("+") not in me.text

        other_tg = new_telegram_id()
        other = await login(on, signed_init_data(settings, other_tg))
        taken = await on.post(
            "/api/v1/me/phone",
            headers=bearer(other),
            json={"contact": signed_contact(settings, other_tg, phone)},
        )
        assert (taken.status_code, taken.json()["code"]) == (409, "phone_taken")
        assert phone.removeprefix("+") not in taken.text

        foreign = await on.post(
            "/api/v1/me/phone",
            headers=bearer(other),
            json={"contact": signed_contact(settings, telegram_id, new_phone())},
        )
        assert (foreign.status_code, foreign.json()["code"]) == (422, "invalid_phone_contact")
        assert foreign.json()["reason"] == "not_own"
