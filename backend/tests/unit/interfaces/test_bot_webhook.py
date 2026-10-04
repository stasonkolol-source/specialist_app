"""Webhook бота (DEVELOPMENT_PLAN 0.25e, ADR-0011): апдейт с верным secret_token доходит до
диспетчера, без него или с чужим — 401 и ничего не обработано; setWebhook — с секретом и узким
allowed_updates; список allowed_updates совпадает с хендлерами."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from aiohttp.test_utils import TestClient, TestServer

from app.entrypoints._wiring import module_bot_routers
from app.interfaces.bot import commands
from app.interfaces.bot.app import ALLOWED_UPDATES
from app.interfaces.bot.webhook import (
    HEALTH_PATH,
    MAX_CONNECTIONS,
    WEBHOOK_PATH,
    SecretTokenHandler,
    apply_webhook,
    create_webhook_app,
    remove_webhook,
    webhook_url,
)

pytestmark = pytest.mark.unit

SECRET = "a" * 32 + "-_" + "9" * 30  # синтетический: тот же алфавит, что у make gen-secret
HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _update(update_id: int) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "date": int(datetime(2026, 10, 4, tzinfo=UTC).timestamp()),
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Ana"},
            "text": "/start",
        },
    }


@pytest.fixture
async def webhook() -> Any:
    """Сервер процесса bot на диспетчере, который только запоминает update_id апдейтов."""
    handled: list[int] = []
    router = Router()

    @router.message()
    async def remember(message: Message, event_update: Any) -> None:
        handled.append(event_update.update_id)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    bot = Bot("123456:TEST_ONLY_synthetic_token")  # сеть не нужна: хендлер Bot API не зовёт
    async with TestClient(TestServer(create_webhook_app(dispatcher, bot, SECRET))) as client:
        yield client, handled


async def test_update_with_the_secret_is_processed(webhook: Any) -> None:
    client, handled = webhook

    response = await client.post(WEBHOOK_PATH, json=_update(7), headers={HEADER: SECRET})

    assert response.status == 200
    assert handled == [7]  # обработан до ответа: handle_in_background=False


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {HEADER: ""},
        {HEADER: "wrong"},
        {HEADER: SECRET[:-1]},
        {HEADER: SECRET + "x"},
        {HEADER: "секрет"},  # не ASCII: compare_digest упал бы TypeError → 500
    ],
    ids=["missing", "empty", "wrong", "prefix", "longer", "non-ascii"],
)
async def test_update_without_the_secret_is_rejected(webhook: Any, headers: dict[str, str]) -> None:
    client, handled = webhook

    response = await client.post(WEBHOOK_PATH, json=_update(8), headers=headers)

    assert response.status == 401
    assert handled == []


async def test_health_check_for_kamal_proxy(webhook: Any) -> None:
    client, _ = webhook

    response = await client.get(HEALTH_PATH)

    assert (response.status, await response.text()) == (200, "OK")


def test_handler_refuses_to_run_without_a_secret() -> None:
    # aiogram без secret_token принимает любой POST
    with pytest.raises(ValueError, match="secret_token"):
        SecretTokenHandler(Dispatcher(), Bot("123456:TEST_ONLY_synthetic_token"), "")


def test_webhook_url_is_under_the_waf_exception() -> None:
    url = webhook_url("https://stage-bot.example.test/")

    assert url == "https://stage-bot.example.test/integrations/telegram/webhook"
    assert WEBHOOK_PATH.startswith("/integrations/telegram/")  # skip-правило WAF stage (0.25b)


@dataclass
class FakeBot:
    """Webhook бота в Telegram: setWebhook и deleteWebhook запоминают вызовы."""

    url: str = ""
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def set_webhook(self, **kwargs: Any) -> bool:
        self.url = kwargs["url"]
        self.calls.append(("set_webhook", kwargs))
        return True

    async def get_webhook_info(self) -> Any:
        return type("WebhookInfo", (), {"url": self.url})()

    async def delete_webhook(self, **kwargs: Any) -> bool:
        self.url = ""
        self.calls.append(("delete_webhook", kwargs))
        return True


async def test_set_webhook_sends_the_secret_and_narrow_updates() -> None:
    bot: Any = FakeBot()

    await apply_webhook(bot, "https://api.example.test/hook", SECRET, ALLOWED_UPDATES)

    assert bot.calls == [
        (
            "set_webhook",
            {
                "url": "https://api.example.test/hook",
                "secret_token": SECRET,
                "allowed_updates": ["message", "callback_query", "my_chat_member"],
                "max_connections": MAX_CONNECTIONS,
                "drop_pending_updates": False,
            },
        )
    ]


async def test_set_webhook_refuses_an_empty_secret() -> None:
    bot: Any = FakeBot()

    with pytest.raises(ValueError, match="secret_token"):
        await apply_webhook(bot, "https://api.example.test/hook", "", ALLOWED_UPDATES)
    assert bot.calls == []


async def test_remove_webhook_only_when_one_is_set() -> None:
    bot: Any = FakeBot()

    assert await remove_webhook(bot) is False
    bot.url = "https://api.example.test/hook"
    assert await remove_webhook(bot) is True
    assert bot.calls == [("delete_webhook", {"drop_pending_updates": False})]


def test_allowed_updates_match_the_handlers() -> None:
    """Новый тип апдейта у хендлера без записи в ALLOWED_UPDATES Telegram просто не пришлёт."""
    dispatcher = Dispatcher()
    for router in [*module_bot_routers(), commands.create_router()]:
        dispatcher.include_router(router)

    assert sorted(dispatcher.resolve_used_update_types()) == sorted(ALLOWED_UPDATES)
