"""Вход, refresh, выход по HTTP (DEVELOPMENT_PLAN 0.15b, ADR-0009)."""

import asyncio
from datetime import timedelta

import httpx
import pytest

from app.platform.kernel.clock import SystemClock

from .conftest import InitData, bearer, login

pytestmark = pytest.mark.integration


async def test_login_returns_tokens_and_user(api: httpx.AsyncClient, init_data: InitData) -> None:
    body = await login(api, init_data(first_name="Ana", last_name="Petrović", username="ana_ns"))

    assert body["token_type"] == "Bearer"  # noqa: S105 — тип токена
    assert body["is_new"] is True
    user = body["user"]
    assert isinstance(user, dict)
    assert user["display_name"] == "Ana Petrović"
    assert user["ui_locale"] == "sr-Latn"
    assert set(user) == {
        "id",
        "display_name",
        "ui_locale",
        "trust_level",
        "phone_verified",
        "created_at",
        "home_city_id",
        "intent",
        "consents",
        "consent_required",
        "can_post_jobs",
        "can_respond",
        "can_message",
        "deletion_scheduled_at",
    }
    assert (user["consents"], user["consent_required"], user["can_post_jobs"]) == ({}, True, False)
    assert user["deletion_scheduled_at"] is None

    again = await login(api, init_data())
    assert again["is_new"] is False
    assert again["user"] == {**user, "display_name": user["display_name"]}


async def test_parallel_logins_of_one_user_all_succeed(
    api: httpx.AsyncClient, init_data: InitData
) -> None:
    """Mini App и бот одного человека входят разом (или клиент повторил запрос): вход не
    отвечает 409 — первый создаёт пользователя, остальные ждут строку и входят."""
    header = {"authorization": f"tma {init_data()}"}

    async def attempt() -> httpx.Response:
        return await api.post("/api/v1/auth/telegram", headers=header)

    first = await asyncio.gather(*(attempt() for _ in range(5)))
    again = await asyncio.gather(*(attempt() for _ in range(5)))

    assert [r.status_code for r in (*first, *again)] == [200] * 10, [r.text for r in first]
    assert sum(r.json()["is_new"] for r in first) == 1
    assert not any(r.json()["is_new"] for r in again)
    assert len({r.json()["user"]["id"] for r in (*first, *again)}) == 1


async def test_expired_init_data_is_401(api: httpx.AsyncClient, init_data: InitData) -> None:
    stale = init_data(auth_date=SystemClock().now() - timedelta(hours=2))
    response = await api.post("/api/v1/auth/telegram", headers={"authorization": f"tma {stale}"})
    assert response.status_code == 401
    assert response.json()["code"] == "init_data_expired"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header", [None, "tma", "Bearer abc", "tma user=1&hash=00", "tma auth_date=1&user=%7B%7D"]
)
async def test_bad_init_data_is_401(api: httpx.AsyncClient, header: str | None) -> None:
    headers = {"authorization": header} if header else {}
    response = await api.post("/api/v1/auth/telegram", headers=headers)
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_init_data"


async def test_refresh_rotates_and_immediate_retry_keeps_session(
    api: httpx.AsyncClient, init_data: InitData
) -> None:
    first = await login(api, init_data())
    second = (
        await api.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    ).json()
    assert second["refresh_token"] != first["refresh_token"]

    retry = await api.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert retry.status_code == 401
    assert retry.json()["code"] == "invalid_refresh_token"
    assert (await api.get("/api/v1/me", headers=bearer(second))).status_code == 200
    third = await api.post("/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert third.status_code == 200


async def test_reuse_after_race_window_revokes_access_too(
    api: httpx.AsyncClient, init_data: InitData, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.identity.domain import session as session_module

    monkeypatch.setattr(session_module, "RACE_WINDOW", timedelta(0))
    first = await login(api, init_data())
    second = (
        await api.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    ).json()

    reused = await api.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reused.json()["code"] == "session_revoked"
    for tokens in (first, second):
        me = await api.get("/api/v1/me", headers=bearer(tokens))
        assert me.status_code == 401
        assert me.json()["code"] == "session_revoked"
    blocked = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert blocked.json()["code"] == "session_revoked"


async def test_logout_revokes_session(api: httpx.AsyncClient, init_data: InitData) -> None:
    tokens = await login(api, init_data())
    assert (await api.post("/api/v1/auth/logout", headers=bearer(tokens))).status_code == 204
    assert (await api.get("/api/v1/me", headers=bearer(tokens))).json()["code"] == "session_revoked"
    refreshed = await api.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.json()["code"] == "session_revoked"


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({}, "not_authenticated"),
        ({"authorization": "Bearer"}, "not_authenticated"),
        ({"authorization": "Basic abc"}, "not_authenticated"),
        ({"authorization": "Bearer not.a.jwt"}, "invalid_token"),
    ],
)
async def test_protected_endpoints_need_bearer(
    api: httpx.AsyncClient, headers: dict[str, str], code: str
) -> None:
    for method, path in (
        ("GET", "/api/v1/me"),
        ("PATCH", "/api/v1/me"),
        ("POST", "/api/v1/auth/logout"),
    ):
        response = await api.request(method, path, headers=headers, json={})
        assert response.status_code == 401, (method, path)
        assert response.json()["code"] == code


async def test_refresh_body_is_validated(api: httpx.AsyncClient) -> None:
    assert (await api.post("/api/v1/auth/refresh", json={})).status_code == 422
    garbage = await api.post("/api/v1/auth/refresh", json={"refresh_token": "garbage"})
    assert garbage.status_code == 401
    assert garbage.json()["code"] == "invalid_refresh_token"


async def test_auth_is_rate_limited_per_ip(api: httpx.AsyncClient, init_data: InitData) -> None:
    statuses = []
    for _ in range(11):
        response = await api.post("/api/v1/auth/refresh", json={"refresh_token": "garbage"})
        statuses.append(response.status_code)
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429
    telegram = await api.post(
        "/api/v1/auth/telegram", headers={"authorization": f"tma {init_data()}"}
    )
    assert telegram.status_code == 429
    assert int(telegram.headers["retry-after"]) >= 1


async def test_auth_endpoints_are_in_openapi(api: httpx.AsyncClient) -> None:
    spec = (await api.get("/api/v1/openapi.json")).json()
    operations = {
        (path, method): op for path, item in spec["paths"].items() for method, op in item.items()
    }
    assert (
        operations[("/api/v1/auth/telegram", "post")]["operationId"]
        == "identity_authenticate_telegram"
    )
    assert operations[("/api/v1/auth/refresh", "post")]["operationId"] == "identity_refresh_session"
    assert operations[("/api/v1/me", "get")]["security"] == [{"HTTPBearer": []}]
    assert "security" not in operations[("/api/v1/auth/telegram", "post")]
    assert {"AuthOut", "TokensOut", "MeOut", "MeUpdateIn", "RefreshIn"} <= set(
        spec["components"]["schemas"]
    )


async def test_authentication_comes_before_validation(api: httpx.AsyncClient) -> None:
    response = await api.patch(
        "/api/v1/me", headers={"if-match": "garbage"}, json={"ui_locale": "de"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"
