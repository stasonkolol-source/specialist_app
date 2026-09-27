"""Бот: /start на фейковом Update (DEVELOPMENT_PLAN 0.22, ADR-0011).

Bot API подменён сессией, которая записывает вызовы: сеть не нужна. БД и Valkey — настоящие
(testcontainers): /start создаёт пользователя тем же кодом, что и вход Mini App.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import Chat, InlineKeyboardMarkup, Message, Update, User
from dishka import AsyncContainer
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from structlog.testing import capture_logs

from app.entrypoints._wiring import make_bot_container, module_bot_routers
from app.interfaces.bot.app import create_dispatcher
from app.modules.growth.application.ports import RECORD_ATTRIBUTION
from app.modules.identity.api import IdentityApi
from app.modules.notifications.application.ports import GRANT_WRITE_ACCESS
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration

MINI_APP = "https://mini.example.test/"


@dataclass
class RecordingSession(BaseSession):
    """Сессия Bot API без сети: запоминает методы и отвечает правдоподобно."""

    calls: list[TelegramMethod[Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__init__()

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 — сигнатура BaseSession
    ) -> Any:
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=len(self.calls),
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        return True

    async def stream_content(
        self, *args: Any, **kwargs: Any
    ) -> AsyncIterator[bytes]:  # pragma: no cover
        yield b""

    async def close(self) -> None:
        return None


@dataclass
class BotHarness:
    bot: Bot
    session: RecordingSession
    dispatcher: Dispatcher
    container: AsyncContainer

    async def send(
        self, telegram_id: int, text_value: str, *, language: str = "ru", name: str = "Ana"
    ) -> SendMessage:
        before = len(self.session.calls)
        await self.dispatcher.feed_update(
            self.bot, self.update(telegram_id, text_value, language=language, name=name)
        )
        replies = [c for c in self.session.calls[before:] if isinstance(c, SendMessage)]
        assert len(replies) == 1, replies
        return replies[0]

    async def send_parallel(self, telegram_id: int, text_value: str, times: int) -> list[str]:
        """`times` одинаковых апдейтов разом, как polling отдаёт накопившиеся; тексты ответов."""
        before = len(self.session.calls)
        updates = [self.update(telegram_id, text_value) for _ in range(times)]
        await asyncio.gather(*(self.dispatcher.feed_update(self.bot, u) for u in updates))
        replies = [c.text for c in self.session.calls[before:] if isinstance(c, SendMessage)]
        assert len(replies) == times, replies
        return replies

    @staticmethod
    def update(
        telegram_id: int, text_value: str, *, language: str = "ru", name: str = "Ana"
    ) -> Update:
        return Update(
            update_id=new_id().int % 2**31,
            message=Message(
                message_id=1,
                date=datetime.now(UTC),
                chat=Chat(id=telegram_id, type="private"),
                from_user=User(
                    id=telegram_id, is_bot=False, first_name=name, language_code=language
                ),
                text=text_value,
            ),
        )


@pytest.fixture
async def harness(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[BotHarness]:
    monkeypatch.setenv("TELEGRAM_MINI_APP_URL", MINI_APP)
    settings = Settings(env_file=None)
    container = make_bot_container(settings)
    session = RecordingSession()
    bot = Bot("8123456789:AAE" + "x" * 32, session=session)
    dispatcher = create_dispatcher(container, await container.get(Redis), module_bot_routers())
    try:
        yield BotHarness(bot=bot, session=session, dispatcher=dispatcher, container=container)
    finally:
        await container.close()


def _button_url(reply: SendMessage) -> str | None:
    markup = reply.reply_markup
    assert isinstance(markup, InlineKeyboardMarkup)
    web_app = markup.inline_keyboard[0][0].web_app
    return web_app.url if web_app else None


async def test_start_registers_user_and_offers_mini_app(harness: BotHarness) -> None:
    telegram_id = 700_000_000 + new_id().int % 10_000_000
    with capture_logs() as logs:
        first = await harness.send(telegram_id, "/start", language="sr", name="Ana")
    assert first.text.startswith("Zdravo, Ana!")
    assert _button_url(first) == MINI_APP

    async with harness.container() as request:
        user = await (await request.get(IdentityApi)).by_telegram(telegram_id)
    assert user is not None
    assert user.display_name == "Ana"

    again = await harness.send(telegram_id, "/start", language="sr")
    assert again.text.startswith("Dobro došao ponovo, Ana!")
    assert str(telegram_id) not in repr(logs)  # в логах только внутренний user_id


async def test_parallel_starts_of_one_user_all_get_welcome(harness: BotHarness) -> None:
    """Апдейты, накопившиеся, пока бот лежал, polling отдаёт разом, и aiogram обрабатывает их
    параллельно; двойное нажатие /start — тоже. Конфликт записи пользователя не должен
    доходить до человека сообщением об ошибке."""
    telegram_id = 700_000_000 + new_id().int % 10_000_000

    first = await harness.send_parallel(telegram_id, "/start", 5)  # новый пользователь
    again = await harness.send_parallel(telegram_id, "/start", 5)  # уже есть: запись входа

    texts = [*first, *again]
    assert all(text.startswith(("Привет, Ana!", "С возвращением, Ana!")) for text in texts), texts
    async with harness.container() as request:
        assert await (await request.get(IdentityApi)).by_telegram(telegram_id) is not None


async def test_start_in_russian_by_default(harness: BotHarness) -> None:
    reply = await harness.send(
        700_000_000 + new_id().int % 10_000_000, "/start", language="de", name="Иван"
    )
    assert reply.text.startswith("Привет, Иван!")


async def test_banned_user_gets_restriction_message(harness: BotHarness) -> None:
    telegram_id = 700_000_000 + new_id().int % 10_000_000
    await harness.send(telegram_id, "/start")
    async with harness.container() as request:
        user = await (await request.get(IdentityApi)).by_telegram(telegram_id)
        engine = await request.get(AsyncEngine)
    assert user is not None
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO identity.restrictions"
                " (id, user_id, kind, reason_code, source, starts_at) VALUES"
                " (uuidv7(), :user_id, 'banned', 'test', 'moderation', now() - interval '1 minute')"
            ),
            {"user_id": user.id},
        )
    reply = await harness.send(telegram_id, "/start")
    assert reply.text == "Это действие для вас сейчас ограничено."


async def test_start_with_deep_link_attributes_user_and_opens_channel(harness: BotHarness) -> None:
    """/start <payload>: атрибуция первого касания (growth) и канал бота (notifications, 1.4b)."""
    telegram_id = 700_000_000 + new_id().int % 10_000_000
    await harness.send(telegram_id, "/start s_02yBkPi1NksSnHWzckDH0V_rAB12CD")
    async with harness.container() as request:
        user = await (await request.get(IdentityApi)).by_telegram(telegram_id)
        engine = await request.get(AsyncEngine)
    assert user is not None

    assert await run_queued(harness.container, RECORD_ATTRIBUTION, user_id=user.id) == 1
    assert await run_queued(harness.container, GRANT_WRITE_ACCESS, user_id=user.id) == 1
    await harness.send(telegram_id, "/start h_rOTHER")  # второе касание
    assert await run_queued(harness.container, RECORD_ATTRIBUTION, user_id=user.id) == 0
    assert await run_queued(harness.container, GRANT_WRITE_ACCESS, user_id=user.id) == 1

    async with engine.connect() as conn:
        attribution = (
            await conn.execute(
                text(
                    "SELECT source, referral_code, entry_point FROM growth.attributions"
                    " WHERE user_id = :user_id"
                ),
                {"user_id": user.id},
            )
        ).one()
        channel = (
            await conn.execute(
                text(
                    "SELECT address, granted_via, disabled_at FROM notifications.channels"
                    " WHERE user_id = :user_id"
                ),
                {"user_id": user.id},
            )
        ).one()
    assert tuple(attribution) == ("specialist", "AB12CD", "bot")
    assert tuple(channel) == (str(telegram_id), "bot_start", None)
