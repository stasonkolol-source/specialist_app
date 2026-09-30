"""Лимитер отправки бота на Valkey (DEVELOPMENT_PLAN 2.3b, ARCHITECTURE §11.2).

25 msg/s на бота и 1 msg/s на чат — общие для всех воркеров, время — часы Valkey. Слот
занимается сразу (модель GCRA, bucket.py): очередь сообщений расходится по слотам за один
проход. После 429 Telegram все слоты — после паузы. Недоступный Valkey не останавливает
отправку.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from app.platform.kernel.ids import new_id
from app.platform.telegram.limiter import ValkeySendLimiter

pytestmark = pytest.mark.integration


@pytest.fixture
async def valkey(valkey_url: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(valkey_url)
    yield client
    await client.aclose()


def limiter(valkey: Redis) -> ValkeySendLimiter:
    return ValkeySendLimiter(valkey, prefix=f"test:{new_id().hex}")  # свои бакеты на тест


async def test_bot_sends_25_at_once_then_every_40_ms(valkey: Redis) -> None:
    send = limiter(valkey)

    slots = [await send.reserve(chat_id, within=3) for chat_id in range(1, 28)]

    assert all(slot.reserved for slot in slots)
    assert [slot.wait for slot in slots[:25]] == [0.0] * 25
    assert 0 < slots[25].wait <= 0.041  # 26-е — через ≈40 мс
    assert 0.04 < slots[26].wait <= 0.081


async def test_one_chat_gets_a_message_a_second(valkey: Redis) -> None:
    send = limiter(valkey)

    first = await send.reserve(42, within=3)
    second = await send.reserve(42, within=3)
    other = await send.reserve(43, within=3)

    assert (first.wait, first.reserved) == (0.0, True)
    assert second.reserved
    assert 0.95 < second.wait <= 1.0  # слот его: уйдёт через секунду
    assert other.wait == 0.0  # другому чату — сразу


async def test_slot_beyond_the_horizon_is_not_taken(valkey: Redis) -> None:
    send = limiter(valkey)
    await send.reserve(42, within=3)

    far = await send.reserve(42, within=0.5)  # ждать секунду — дольше горизонта
    near = await send.reserve(42, within=3)

    assert (far.reserved, round(far.wait)) == (False, 1)
    assert near.reserved
    assert near.wait < 1.0  # не занятый слот не сдвинул очередь


async def test_competing_workers_share_the_buckets(valkey: Redis) -> None:
    prefix = f"test:{new_id().hex}"
    workers = [ValkeySendLimiter(valkey, prefix=prefix) for _ in range(4)]

    now = await asyncio.gather(
        *(workers[chat % 4].reserve(chat, within=0) for chat in range(40))  # 4 воркера разом
    )
    later = await asyncio.gather(
        *(workers[chat % 4].reserve(chat, within=3) for chat in range(100, 140))
    )

    assert sum(1 for slot in now if slot.reserved) == 25  # ровно 25: ни больше, ни меньше
    assert all(slot.reserved for slot in later)
    waits = sorted(slot.wait for slot in later)
    assert waits[-1] == pytest.approx(40 * 0.04, abs=0.05)  # слоты подряд, без провалов


async def test_flood_wait_pauses_everyone_and_is_never_shortened(valkey: Redis) -> None:
    send = limiter(valkey)

    await send.pause(5)
    await send.pause(1)  # более короткий 429 паузу не укорачивает
    slot = await send.reserve(7, within=3)

    assert not slot.reserved
    assert 4 < slot.wait <= 5


async def test_unavailable_valkey_does_not_stop_sending() -> None:
    broken = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    try:
        send = ValkeySendLimiter(broken)
        slot = await send.reserve(42, within=3)
        assert (slot.wait, slot.reserved) == (0.0, True)
        await send.pause(3)  # и не падает
    finally:
        await broken.aclose()


async def test_waiting_for_a_chat_does_not_hold_up_the_bot(valkey: Redis) -> None:
    send = limiter(valkey)
    await send.reserve(42, within=3)

    second = await send.reserve(42, within=3)  # ждёт свой чат секунду
    others = [await send.reserve(chat, within=3) for chat in range(100, 124)]
    bot = await send.reserve_bot(within=3)  # его слот бота — в момент отправки

    assert (second.reserved, second.bot_pending) == (True, True)
    assert [slot.wait for slot in others] == [0.0] * 24  # остальные чаты — сразу
    assert bot.reserved
    assert bot.wait < 0.05
