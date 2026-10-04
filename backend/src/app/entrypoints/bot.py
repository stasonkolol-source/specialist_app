"""Процесс бота (DEVELOPMENT_PLAN 0.22, 0.25e): `python -m app.entrypoints.bot`.

Режим — TELEGRAM_UPDATES: в dev — long polling; на stage и prod — webhook в этом же процессе
(ADR-0011: aiohttp-сервер aiogram за kamal-proxy, interfaces/bot/webhook.py). Роутеры — из
modules/<m>/bot/handlers.py, пользователь и локаль — прослойками interfaces/bot.
"""

import asyncio
import signal

import structlog
from aiogram import Bot, Dispatcher
from aiohttp import web
from prometheus_client import CollectorRegistry
from redis.asyncio import Redis

from app.entrypoints._wiring import make_bot_container, module_bot_routers
from app.interfaces.bot.app import ALLOWED_UPDATES, create_dispatcher
from app.interfaces.bot.webhook import apply_webhook, create_webhook_app, webhook_url
from app.platform.i18n.translator import Translator
from app.platform.observability.logging import configure_logging
from app.platform.observability.metrics import metrics_server
from app.platform.observability.sentry import init_sentry
from app.platform.settings import Settings, UpdatesMode, describe, webhook_base_url

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
        log.info("bot_started", username=me.username, **describe(settings))
        # метрики (429 Bot API) — в обоих режимах; порт METRICS_PORT не совпадает с портом webhook
        with metrics_server(settings.metrics, await container.get(CollectorRegistry)):
            if settings.telegram.updates is UpdatesMode.WEBHOOK:
                await serve_webhook(settings, bot, dispatcher)
                return
            await bot.delete_webhook(drop_pending_updates=False)
            await dispatcher.start_polling(
                bot, allowed_updates=list(ALLOWED_UPDATES), handle_signals=True
            )
    finally:
        await container.close()


async def serve_webhook(settings: Settings, bot: Bot, dispatcher: Dispatcher) -> None:
    """Webhook-сервер до SIGTERM или SIGINT (Kamal останавливает контейнер): начатые апдейты
    дорабатываются, новые kamal-proxy уже шлёт в новый контейнер."""
    secret = settings.telegram.webhook_secret
    token = secret.get_secret_value() if secret else ""  # пустой отвергнет SecretTokenHandler
    url = webhook_url(webhook_base_url(settings.app, settings.telegram))

    async def set_webhook(bot: Bot) -> None:
        # Каждый старт (деплой) выставляет webhook заново: «webhook выставит деплой» (K17),
        # новый секрет вступает в силу сам. Ошибка роняет процесс — Docker перезапустит его, а
        # Kamal не переключит трафик на контейнер без /up.
        await apply_webhook(bot, url, token, ALLOWED_UPDATES)
        log.info("bot_webhook_set", url=url, allowed_updates=list(ALLOWED_UPDATES))

    dispatcher.startup.register(set_webhook)
    runner = web.AppRunner(create_webhook_app(dispatcher, bot, token), access_log=None)
    await runner.setup()  # startup диспетчера: setWebhook
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    try:
        await web.TCPSite(runner, settings.app.web_host, settings.app.web_port).start()
        log.info("bot_webhook_listening", host=settings.app.web_host, port=settings.app.web_port)
        await stop.wait()
    finally:
        await runner.cleanup()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
