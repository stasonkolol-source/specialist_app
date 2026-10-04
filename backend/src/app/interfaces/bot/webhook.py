"""Приём апдейтов через webhook (ADR-0011, DEVELOPMENT_PLAN 0.25e): процесс bot поднимает
aiohttp-сервер aiogram за kamal-proxy, web апдейтов не видит — всплеск в боте не тормозит API.

- Путь `/integrations/telegram/webhook` (ARCHITECTURE §8.5) на своём хосте процесса bot
  (TELEGRAM_WEBHOOK_BASE_URL: kamal-proxy не отдаёт один хост с TLS двум ролям) — под
  skip-правилом WAF Cloudflare для `/integrations/telegram/`. Защищает не адрес, а секрет:
  Telegram присылает `secret_token` в заголовке X-Telegram-Bot-Api-Secret-Token; без него или с
  чужим — 401, апдейт в диспетчер не попадает. Сравнение — за постоянное время
  (`secrets.compare_digest` в aiogram).
- Апдейт обрабатывается до ответа (`handle_in_background=False`): Telegram держит не больше
  MAX_CONNECTIONS запросов разом — это и есть предел нагрузки на пул БД; исключение мимо
  ErrorMiddleware даёт 500, и Telegram повторит апдейт (at-least-once, хендлеры идемпотентны —
  как при polling, который отдаёт накопленное разом); при деплое kamal-proxy и aiohttp
  дожидаются начатых запросов, а не обрывают фоновые задачи.
- `/up` — healthcheck kamal-proxy, как у web.
"""

from collections.abc import Sequence
from typing import Final

import structlog
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

log = structlog.get_logger(__name__)

WEBHOOK_PATH: Final = "/integrations/telegram/webhook"
HEALTH_PATH: Final = "/up"
MAX_CONNECTIONS: Final = 10
"""Одновременных запросов от Telegram (у Bot API по умолчанию 40): каждый держит сессию БД, пул
процесса — DB_POOL_SIZE = 10. Лишние апдейты ждут у Telegram, а не в очереди пула."""


def webhook_url(base_url: str) -> str:
    """Адрес webhook: адрес процесса bot (settings.webhook_base_url) + WEBHOOK_PATH."""
    return base_url.rstrip("/") + WEBHOOK_PATH


class SecretTokenHandler(SimpleRequestHandler):
    """SimpleRequestHandler aiogram с обязательным секретом: без секрета он принял бы любой POST.

    Заголовок не из ASCII отклоняется до сравнения: `compare_digest` на нём падает TypeError, и
    вместо 401 был бы 500 — а такой заголовок заведомо не от Telegram."""

    def __init__(self, dispatcher: Dispatcher, bot: Bot, secret: str) -> None:
        if not secret:
            raise ValueError("webhook needs a secret_token")
        super().__init__(dispatcher, bot, handle_in_background=False, secret_token=secret)

    def verify_secret(self, telegram_secret_token: str, bot: Bot) -> bool:
        valid = telegram_secret_token.isascii() and super().verify_secret(
            telegram_secret_token, bot
        )
        if not valid:
            # значение заголовка не логируем: это мог быть устаревший, но настоящий секрет
            log.info("bot_webhook_rejected", has_token=bool(telegram_secret_token))
        return valid


def create_webhook_app(dispatcher: Dispatcher, bot: Bot, secret: str) -> web.Application:
    """aiohttp-приложение процесса bot: webhook, `/up` и startup/shutdown диспетчера."""
    app = web.Application()
    SecretTokenHandler(dispatcher, bot, secret).register(app, path=WEBHOOK_PATH)
    app.router.add_get(HEALTH_PATH, _up)
    setup_application(app, dispatcher, bot=bot)
    return app


async def _up(_: web.Request) -> web.Response:
    return web.Response(text="OK")


async def apply_webhook(bot: Bot, url: str, secret: str, allowed_updates: Sequence[str]) -> None:
    """Выставить webhook с секретом и узким allowed_updates. Сверить с getWebhookInfo, как
    профиль, нельзя — секрет Telegram не возвращает, — поэтому setWebhook всегда: он идемпотентен,
    а новый секрет так вступает в силу. Накопившиеся апдейты не сбрасываем."""
    if not secret:
        raise ValueError("webhook needs a secret_token")
    await bot.set_webhook(
        url=url,
        secret_token=secret,
        allowed_updates=list(allowed_updates),
        max_connections=MAX_CONNECTIONS,
        drop_pending_updates=False,
    )


async def remove_webhook(bot: Bot) -> bool:
    """Снять webhook (polling без этого не получает апдейтов); True — был и снят."""
    if not (await bot.get_webhook_info()).url:
        return False
    await bot.delete_webhook(drop_pending_updates=False)
    return True
