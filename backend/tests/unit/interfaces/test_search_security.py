"""Избранное требует входа до проверки параметров, публичный каталог — нет."""

import pytest

from app.interfaces.http.app import openapi_spec
from app.modules.search.http.router import router
from app.platform.settings import Settings
from tests.plugins.http import http_client

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("authorization", [None, "Bearer invalid"])
async def test_favorites_authenticate_before_validating_profile_id(
    offline_settings: Settings, method: str, authorization: str | None
) -> None:
    headers = {"Authorization": authorization} if authorization is not None else {}
    async with http_client(offline_settings, router) as client:
        response = await client.request(
            method, "/api/v1/me/favorites/profile/not-a-uuid", headers=headers
        )
    assert response.status_code == 401


def test_favorites_require_bearer_in_openapi() -> None:
    paths = openapi_spec([router])["paths"]
    for path, method in (
        ("/api/v1/me/favorites", "get"),
        ("/api/v1/me/favorites/profile/{profile_id}", "put"),
        ("/api/v1/me/favorites/profile/{profile_id}", "delete"),
    ):
        assert paths[path][method].get("security") == [{"HTTPBearer": []}]
    assert not paths["/api/v1/specialists"]["get"].get("security")
