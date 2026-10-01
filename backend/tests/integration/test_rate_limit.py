"""Лимиты в Valkey (DEVELOPMENT_PLAN 0.13b, ARCHITECTURE §13.3)."""

import contextlib
from collections.abc import AsyncIterator

import pytest
from dishka import AsyncContainer
from fastapi import Depends
from structlog.testing import capture_logs

from app.entrypoints._wiring import make_web_container
from app.modules.moderation.application.ports import RateLimitOverflows
from app.platform.http.ratelimit import RateLimit
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import RateLimitedError
from app.platform.kernel.ids import UserId, new_id
from app.platform.ratelimit import USER_SUBJECT, Rate, RateLimiter, user_subject
from app.platform.settings import Settings
from tests.plugins.http import http_client, sample_router

pytestmark = pytest.mark.integration

BURST = Rate("test.burst", "3/minute")

router = sample_router()


@router.get("/burst", dependencies=[Depends(RateLimit(BURST))])
async def burst() -> dict[str, str]:
    return {"status": "ok"}


@pytest.fixture
async def container(settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = make_web_container(settings)
    try:
        yield container
    finally:
        await container.close()


async def test_limiter_counts_per_subject_and_records_exceeded(container: AsyncContainer) -> None:
    limiter = await container.get(RateLimiter)
    today = (await container.get(Clock)).now().date()
    subject, other = f"user:{new_id()}", f"user:{new_id()}"

    remaining = [(await limiter.hit(BURST, subject)).remaining for _ in range(3)]
    assert remaining == [2, 1, 0]
    for _ in range(2):
        with pytest.raises(RateLimitedError) as caught:
            await limiter.hit(BURST, subject)
        assert 1 <= caught.value.retry_after <= 60
        assert caught.value.limit == 3

    assert (await limiter.hit(BURST, other)).remaining == 2
    assert await limiter.exceeded(subject, today) == {"test.burst": 2}
    assert await limiter.exceeded(other, today) == {}


async def test_moderation_reads_every_users_exceeded_counters(container: AsyncContainer) -> None:
    limiter = await container.get(RateLimiter)
    today = (await container.get(Clock)).now().date()
    user = new_id()
    subject = user_subject(user)
    for _ in range(4):
        with contextlib.suppress(RateLimitedError):
            await limiter.hit(BURST, subject)
    with contextlib.suppress(RateLimitedError):
        await limiter.hit(BURST, f"ip:10.9.{new_id().int % 250}.1")

    users = await limiter.exceeded_on(today, prefix=USER_SUBJECT)
    overflows = await (await container.get(RateLimitOverflows)).by_user(today)

    assert users[subject] == {"test.burst": 1}
    assert not any(key.startswith("ip:") for key in users)
    assert overflows[UserId(user)] == {"test.burst": 1}


async def test_http_limit_sets_headers_and_answers_429(settings: Settings) -> None:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.7"
    async with http_client(settings, router, client_ip=ip) as client:
        responses = [await client.get("/api/v1/test/burst") for _ in range(4)]

    assert [r.status_code for r in responses] == [200, 200, 200, 429]
    assert [r.headers["ratelimit-remaining"] for r in responses] == ["2", "1", "0", "0"]
    assert {r.headers["ratelimit-limit"] for r in responses} == {"3"}
    limited = responses[-1]
    assert limited.headers["content-type"] == "application/problem+json"
    assert limited.json()["code"] == "rate_limited"
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    assert limited.headers["ratelimit-reset"] == limited.headers["retry-after"]


async def test_limit_fails_open_without_valkey(offline_settings: Settings) -> None:
    async with http_client(offline_settings, router) as client:
        with capture_logs() as logs:
            response = await client.get("/api/v1/test/burst")
    assert response.status_code == 200
    assert any(entry["event"] == "ratelimit_storage_unavailable" for entry in logs)
