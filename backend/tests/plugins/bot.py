"""Бот в тестах: диспетчер как в процессе бота на фейковых Update (ADR-0011).

Bot API подменён сессией, которая записывает вызовы: сеть не нужна. БД и Valkey — настоящие
(testcontainers). Роутеры — всех модулей, как в процессе бота.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher, Router
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageText, GetMe, SendMessage, TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    ChatMemberBanned,
    ChatMemberLeft,
    ChatMemberMember,
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    Message,
    PhotoSize,
    Update,
    User,
)
from dishka import AsyncContainer
from redis.asyncio import Redis

from app.entrypoints._wiring import make_bot_container, module_bot_routers
from app.interfaces.bot.app import create_dispatcher
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings

MINI_APP = "https://mini.example.test/"


@dataclass
class RecordingSession(BaseSession):
    """Сессия Bot API без сети: запоминает методы и отвечает правдоподобно."""

    username: str = "sosed_test_bot"
    """Имя бота в getMe: команду `/start@<бот>` в группе фильтр сверяет с ним."""
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
        if isinstance(method, GetMe):
            return User(id=bot.id, is_bot=True, first_name="Sosedi", username=self.username)
        if isinstance(method, SendMessage | EditMessageText):
            return Message(
                message_id=len(self.calls),
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id or 0), type="private"),
                text=method.text,
            )
        return True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,  # noqa: ASYNC109 — сигнатура BaseSession
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes]:  # pragma: no cover
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

    async def feed(self, telegram_id: int, message: Message) -> list[TelegramMethod[Any]]:
        """Произвольное сообщение от пользователя (служебное, медиа): вызовы Bot API в ответ."""
        before = len(self.session.calls)
        user = User(id=telegram_id, is_bot=False, first_name="Ana", language_code="ru")
        update = Update(
            update_id=new_id().int % 2**31, message=message.model_copy(update={"from_user": user})
        )
        await self.dispatcher.feed_update(self.bot, update)
        return self.session.calls[before:]

    async def press(
        self,
        telegram_id: int,
        data: str,
        *,
        markup: InlineKeyboardMarkup | None = None,
        caption: str | None = None,
    ) -> list[TelegramMethod[Any]]:
        """Нажатие инлайн-кнопки под сообщением бота (с клавиатурой `markup`, если задана; с
        `caption` — под фото с этой подписью): вызовы Bot API в ответ."""
        before = len(self.session.calls)
        chat = Chat(id=telegram_id, type="private")
        user = User(id=telegram_id, is_bot=False, first_name="Ana", language_code="ru")
        if caption is None:
            message = Message(
                message_id=1, date=datetime.now(UTC), chat=chat, text="…", reply_markup=markup
            )
        else:
            photo = PhotoSize(file_id="photo", file_unique_id="photo", width=800, height=600)
            message = Message(
                message_id=1,
                date=datetime.now(UTC),
                chat=chat,
                photo=[photo],
                caption=caption,
                reply_markup=markup,
            )
        callback = CallbackQuery(
            id=str(new_id().int % 2**31),
            from_user=user,
            chat_instance="1",
            data=data,
            message=message,
        )
        await self.dispatcher.feed_update(
            self.bot, Update(update_id=new_id().int % 2**31, callback_query=callback)
        )
        return self.session.calls[before:]

    async def member_status(
        self, telegram_id: int, *, blocked: bool, at: datetime | None = None
    ) -> list[TelegramMethod[Any]]:
        """Пользователь остановил (`kicked`) или снова запустил (`member`) бота: апдейт
        `my_chat_member` личного чата. `at` — дата апдейта (у Telegram — до секунды)."""
        before = len(self.session.calls)
        user = User(id=telegram_id, is_bot=False, first_name="Ana", language_code="ru")
        bot_user = User(id=self.bot.id, is_bot=True, first_name="Sosedi")
        old: Any = ChatMemberMember(user=bot_user)
        new: Any = ChatMemberBanned(user=bot_user, until_date=datetime.fromtimestamp(0, UTC))
        if not blocked:
            old, new = new, old
        update = Update(
            update_id=new_id().int % 2**31,
            my_chat_member=ChatMemberUpdated(
                chat=Chat(id=telegram_id, type="private"),
                from_user=user,
                date=at or datetime.now(UTC),
                old_chat_member=old,
                new_chat_member=new,
            ),
        )
        await self.dispatcher.feed_update(self.bot, update)
        return self.session.calls[before:]

    async def bot_added(self, telegram_id: int, chat: Chat) -> list[TelegramMethod[Any]]:
        """Пользователь добавил бота в группу `chat`: апдейт `my_chat_member` (left → member)."""
        before = len(self.session.calls)
        user = User(id=telegram_id, is_bot=False, first_name="Ana", language_code="ru")
        bot_user = User(id=self.bot.id, is_bot=True, first_name="Sosedi")
        update = Update(
            update_id=new_id().int % 2**31,
            my_chat_member=ChatMemberUpdated(
                chat=chat,
                from_user=user,
                date=datetime.now(UTC),
                old_chat_member=ChatMemberLeft(user=bot_user),
                new_chat_member=ChatMemberMember(user=bot_user),
            ),
        )
        await self.dispatcher.feed_update(self.bot, update)
        return self.session.calls[before:]

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


@asynccontextmanager
async def bot_harness(
    monkeypatch: pytest.MonkeyPatch, *extra: Router, **env: str
) -> AsyncIterator[BotHarness]:
    """Диспетчер как в процессе бота: роутеры модулей, общие команды. Bot — из DI (HTML по
    умолчанию, как в проде), только сессия Bot API подменена записью вызовов."""
    monkeypatch.setenv("TELEGRAM_MINI_APP_URL", MINI_APP)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    settings = Settings(env_file=None)
    container = make_bot_container(settings)
    session = RecordingSession(username=settings.telegram.bot_username)
    bot = await container.get(Bot)
    bot.session = session
    routers = [*module_bot_routers(), *extra]
    dispatcher = create_dispatcher(container, await container.get(Redis), routers)
    try:
        yield BotHarness(bot=bot, session=session, dispatcher=dispatcher, container=container)
    finally:
        await container.close()
