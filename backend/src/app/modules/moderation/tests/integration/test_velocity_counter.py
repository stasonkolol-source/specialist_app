"""Счётчики velocity в Valkey (DEVELOPMENT_PLAN 2.4): различные участники в окне, повтор не
считается, окно — с первого добавления; недоступный Valkey — None (fail open)."""

from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from redis.asyncio import Redis
from structlog.testing import capture_logs

from app.modules.moderation.infrastructure.velocity import ValkeyVelocityCounter
from app.platform.kernel.ids import new_id

pytestmark = pytest.mark.integration


@pytest.fixture
async def valkey(valkey_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(valkey_url)
    yield client
    await client.aclose()


async def test_counts_distinct_members_within_the_window(valkey: Redis) -> None:
    prefix = f"test:{new_id().hex}:"
    counter = ValkeyVelocityCounter(valkey, prefix=prefix)
    window = timedelta(hours=1)

    counts = [
        await counter.add("same_text_accounts:abc", member, window=window)
        for member in ("u1", "u2", "u1", "u3")
    ]

    assert counts == [1, 2, 2, 3]
    ttl = await valkey.ttl(f"{prefix}same_text_accounts:abc")
    assert 3590 < ttl <= 3600


async def test_window_starts_at_the_first_member(valkey: Redis) -> None:
    prefix = f"test:{new_id().hex}:"
    counter = ValkeyVelocityCounter(valkey, prefix=prefix)
    await counter.add("k", "u1", window=timedelta(seconds=100))
    await valkey.expire(f"{prefix}k", 5)  # окно почти прошло

    await counter.add("k", "u2", window=timedelta(seconds=100))

    assert await valkey.ttl(f"{prefix}k") <= 5  # новый участник окно не продлевает


async def test_unreachable_valkey_is_fail_open() -> None:
    client = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    counter = ValkeyVelocityCounter(client)
    try:
        with capture_logs() as logs:
            count = await counter.add("k", "u1", window=timedelta(hours=1))
    finally:
        await client.aclose()

    assert count is None
    assert [entry["event"] for entry in logs] == ["velocity_unavailable"]
