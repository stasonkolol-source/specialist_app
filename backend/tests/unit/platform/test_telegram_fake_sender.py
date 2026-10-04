"""Фейковый отправитель нагрузочного прогона (DEVELOPMENT_PLAN 8.3): лимитер и горизонт — как у
настоящего, вместо Bot API — пауза с его латентностью."""

import random
import statistics
from dataclasses import dataclass, field

import pytest

from app.platform.kernel.errors import RateLimitedError
from app.platform.telegram.aiogram_sender import HORIZON
from app.platform.telegram.fake_sender import (
    LATENCY_CAP,
    LATENCY_MEDIAN,
    FakeTelegramSender,
    bot_api_latency,
)
from app.platform.telegram.port import AppButton, OutgoingMessage, Slot

pytestmark = pytest.mark.unit

MESSAGE = OutgoingMessage(
    chat_id=42, text="Новая заявка", buttons=(AppButton(text="Открыть", url="https://app.test/"),)
)


@dataclass
class Limiter:
    wait: float = 0.0
    chat_bound: bool = False
    reserved: list[int] = field(default_factory=list)
    bot_reserved: int = 0

    async def reserve(self, chat_id: int, *, within: float) -> Slot:
        self.reserved.append(chat_id)
        return Slot(wait=self.wait, reserved=self.wait <= within, bot_pending=self.chat_bound)

    async def reserve_bot(self, *, within: float) -> Slot:
        self.bot_reserved += 1
        return Slot(wait=0.0, reserved=True)

    async def pause(self, seconds: float) -> None:  # pragma: no cover — 429 у фейка не бывает
        raise AssertionError


@dataclass
class Latency:
    seconds: float = 0.0
    calls: int = 0

    def __call__(self) -> float:
        self.calls += 1
        return self.seconds


async def test_send_takes_a_limiter_slot_and_waits_the_bot_api_latency() -> None:
    limiter, latency = Limiter(), Latency()
    telegram = FakeTelegramSender(limiter, latency=latency)

    first = await telegram.send(MESSAGE)
    second = await telegram.send(MESSAGE)

    assert limiter.reserved == [42, 42]
    assert latency.calls == 2
    assert second.message_id > first.message_id


async def test_chat_bound_slot_then_takes_the_bot_slot_like_the_real_sender() -> None:
    limiter = Limiter(chat_bound=True)
    telegram = FakeTelegramSender(limiter, latency=Latency())

    await telegram.send(MESSAGE)

    assert limiter.bot_reserved == 1


async def test_far_slot_goes_back_to_the_queue_without_sending() -> None:
    latency = Latency()
    telegram = FakeTelegramSender(Limiter(wait=HORIZON + 7.5), latency=latency)

    with pytest.raises(RateLimitedError) as caught:
        await telegram.send(MESSAGE)

    assert caught.value.retry_after == 8  # как у aiogram_sender: вернётся ближе к сроку
    assert latency.calls == 0


async def test_editing_buttons_uses_the_same_limiter() -> None:
    limiter, latency = Limiter(), Latency()

    await FakeTelegramSender(limiter, latency=latency).edit_buttons(7, 1001, ())

    assert (limiter.reserved, latency.calls) == ([7], 1)


def test_latency_looks_like_bot_api_and_has_no_endless_tail() -> None:
    sample = bot_api_latency(random.Random(8))  # noqa: S311 — форма задержки, не криптография
    values = [sample() for _ in range(5000)]

    assert statistics.median(values) == pytest.approx(LATENCY_MEDIAN, rel=0.1)
    assert min(values) > 0
    assert max(values) <= LATENCY_CAP
