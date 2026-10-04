"""Процесс бота (DEVELOPMENT_PLAN 0.22): `python -m app.entrypoints.bot`.

В dev — long polling; на stage и prod — webhook в процессе web (шаг 0.25e). Роутеры —
из modules/<m>/bot/handlers.py, пользователь и локаль — прослойками interfaces/bot.
"""

import asyncio

import structlog
from aiogram import Bot
from prometheus_client import CollectorRegistry
from redis.asyncio import Redis

from app.entrypoints._wiring import make_bot_container, module_bot_routers
from app.interfaces.bot.app import create_dispatcher
from app.platform.i18n.translator import Translator
from app.platform.observability.logging import configure_logging
from app.platform.observability.metrics import metrics_server
from app.platform.observability.sentry import init_sentry
from app.platform.settings import Settings, describe

log = structlog.get_logger(__name__)


async def run() -> None:
    settings = Settings()
    configure_logging(settings.app)
    init_sentry(settings, process="bot")
    container = make_bot_container(settings, Translator.load())
    try:
        bot = await container.get(Bot)
        dispatcher = create_dispatcher(container, await container.get(Redis), module_bot_routers())
        me = await bot.get_me()
        log.info("bot_started", username=me.username, mode="polling", **describe(settings))
        await bot.delete_webhook(drop_pending_updates=False)
        with metrics_server(settings.metrics, await container.get(CollectorRegistry)):
            await dispatcher.start_polling(
                bot, allowed_updates=dispatcher.resolve_used_update_types(), handle_signals=True
            )
    finally:
        await container.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
