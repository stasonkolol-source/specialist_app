"""Фейковый отправитель Telegram для нагрузочного прогона на stage (DEVELOPMENT_PLAN 8.3).

Синтетические пользователи прогона — демо-ID `seed-demo`: чатов с ними у Bot API нет, настоящий
отправитель получил бы 400 «chat not found» и выключил бы им канал, а рассылка заявки шла бы со
скоростью ошибок, а не доставки. Фейк проходит тот же путь, что и aiogram_sender.py: слот того же
лимитера в Valkey (25 msg/s на бота, 1 msg/s на чат, горизонт и RateLimitedError — `take_slot`),
затем вместо вызова Bot API — пауза с его латентностью. Поэтому рассылка заявки 10 000
подписчикам идёт с реальной скоростью (≈ 6 мин) и видно, мешает ли она приоритетным
уведомлениям. Наружу ничего не уходит.

Включается TELEGRAM_FAKE_SENDER=true (di.py); на проде процесс с ним не стартует (settings.py).
"""

import asyncio
import itertools
import math
import random
from collections.abc import Callable

from app.platform.telegram.aiogram_sender import take_slot
from app.platform.telegram.port import ButtonLine, OutgoingMessage, SendLimiter, SentMessage

LATENCY_MEDIAN = 0.08
"""Медиана ответа sendMessage из Германии, секунды. [Допущение]: замер на stage (3.3) уточнит."""
LATENCY_SIGMA = 0.5
"""Разброс логнормального распределения: p95 ≈ 0,18 с, p99 ≈ 0,26 с."""
LATENCY_CAP = 2.0
"""Хвост длиннее не моделируем: таймауты и 5xx Bot API — не предмет прогона."""


def bot_api_latency(rng: random.Random) -> Callable[[], float]:
    """Латентность вызова Bot API: логнормальная, как у сетевых вызовов, с отсечкой хвоста."""

    def sample() -> float:
        return min(LATENCY_CAP, rng.lognormvariate(math.log(LATENCY_MEDIAN), LATENCY_SIGMA))

    return sample


class FakeTelegramSender:
    def __init__(self, limiter: SendLimiter, *, latency: Callable[[], float] | None = None) -> None:
        self._limiter = limiter
        # не криптография: только форма задержки
        self._latency = latency or bot_api_latency(random.Random())  # noqa: S311
        self._ids = itertools.count(1)

    async def send(self, message: OutgoingMessage) -> SentMessage:
        await take_slot(self._limiter, message.chat_id)
        await asyncio.sleep(self._latency())
        return SentMessage(message_id=next(self._ids))

    async def edit_buttons(
        self,
        chat_id: int,
        message_id: int,  # noqa: ARG002 — сигнатура порта: править нечего, сообщения не было
        buttons: tuple[ButtonLine, ...],  # noqa: ARG002
    ) -> None:
        await take_slot(self._limiter, chat_id)
        await asyncio.sleep(self._latency())
