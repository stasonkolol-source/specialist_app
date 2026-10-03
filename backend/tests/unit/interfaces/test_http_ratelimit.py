"""Заголовки лимитов сохраняются и у готовых ответов, включая условный ответ 304."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import Depends, Request, Response

from app.platform.http.caching import cached_json
from app.platform.http.ratelimit import GuestOrUserRateLimit, RateLimit
from app.platform.kernel.errors import RateLimitedError
from app.platform.ratelimit import Rate, RateLimiter, RateStatus
from app.platform.settings import Settings
from tests.plugins.http import http_client, sample_router

pytestmark = pytest.mark.unit

RATE = Rate("test.headers", "60/minute")


@pytest.fixture(params=[RateLimit(RATE), GuestOrUserRateLimit(guest=RATE, user=RATE)])
async def client(
    request: pytest.FixtureRequest,
    offline_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setattr(
        RateLimiter,
        "hit",
        AsyncMock(return_value=RateStatus(limit=60, remaining=59, reset_after=30)),
    )
    router = sample_router()

    @router.get("/limited/{kind}", dependencies=[Depends(request.param)], response_model=None)
    async def limited(kind: str, request: Request) -> Response | dict[str, bool]:
        if kind == "cached":
            return cached_json(request, {"ok": True}, max_age=60)
        if kind == "empty":
            return Response(status_code=204)
        if kind == "exceeded":
            raise RateLimitedError(retry_after=120, limit=5)
        return {"ok": True}

    async with http_client(offline_settings, router) as client:
        yield client


@pytest.mark.parametrize(("kind", "status"), [("json", 200), ("cached", 200), ("empty", 204)])
async def test_rate_headers_survive_response_type(
    client: httpx.AsyncClient, kind: str, status: int
) -> None:
    response = await client.get(f"/api/v1/test/limited/{kind}")
    assert response.status_code == status
    assert response.headers["ratelimit-limit"] == "60"
    assert response.headers["ratelimit-remaining"] == "59"
    assert response.headers["ratelimit-reset"] == "30"


async def test_rate_headers_survive_not_modified(client: httpx.AsyncClient) -> None:
    first = await client.get("/api/v1/test/limited/cached")
    response = await client.get(
        "/api/v1/test/limited/cached", headers={"if-none-match": first.headers["etag"]}
    )
    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["ratelimit-limit"] == "60"
    assert response.headers["ratelimit-remaining"] == "59"
    assert response.headers["ratelimit-reset"] == "30"


async def test_exceeded_limit_headers_take_precedence(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/test/limited/exceeded")
    assert response.status_code == 429
    assert response.headers["ratelimit-limit"] == "5"
    assert response.headers["ratelimit-remaining"] == "0"
    assert response.headers["ratelimit-reset"] == response.headers["retry-after"] == "120"
