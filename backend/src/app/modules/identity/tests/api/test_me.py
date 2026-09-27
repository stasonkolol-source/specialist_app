"""GET и PATCH /me (DEVELOPMENT_PLAN 0.15b)."""

import httpx
import pytest

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
