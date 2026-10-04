"""Счётчик 429 Bot API (DEVELOPMENT_PLAN 3.3, ARCHITECTURE §16.5) — прослойка сессии aiogram.

Прослойка стоит на сессии общего `Bot` процесса, поэтому видит каждый вызов Bot API:
рассылку уведомлений (aiogram_sender.py), ответы хендлеров бота, команды CLI. Паузу всем
отправкам после 429 по-прежнему ставит отправитель через лимитер; здесь — только метрика.
"""

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods.base import Response, TelegramMethod, TelegramType

from app.platform.observability.metrics import TelegramMetrics


class FloodWaitMetrics(BaseRequestMiddleware):
    def __init__(self, metrics: TelegramMetrics) -> None:
        self._metrics = metrics

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        try:
            return await make_request(bot, method)
        except TelegramRetryAfter as exc:
            self._metrics.observe_flood_wait(
                method=method.__api_method__, retry_after=exc.retry_after
            )
            raise
