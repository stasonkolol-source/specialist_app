"""/settings в боте (DEVELOPMENT_PLAN 4.9): язык, уведомления в боте по группам и тихие часы,
«Все настройки» (S43) и «Удалить аккаунт» (S45).

Бот — диспетчер процесса бота на фейковых Update, Bot API записывается (tests/plugins/bot.py);
БД и Valkey — настоящие, данные коммитятся. Настройки читаем тем же query-сервисом, что и
`GET /me/notification-settings`: что переключил бот, то видит S43.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from aiogram.methods import EditMessageReplyMarkup, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import InlineKeyboardMarkup
from tests.plugins.bot import BotHarness, bot_harness

from app.modules.identity.api import IdentityApi
from app.modules.notifications.application.ports import NotificationQuery
from app.modules.notifications.domain.catalog import Channel, EventGroup
from app.modules.notifications.domain.settings import NotificationSettings
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings

pytestmark = pytest.mark.integration

LANGUAGES_RU = [("✅ Русский", "lang:ru"), ("Srpski", "lang:sr-Latn"), ("Српски", "lang:sr-Cyrl")]


@pytest.fixture
async def harness(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[BotHarness]:
    async with bot_harness(monkeypatch) as harness:
        yield harness


def telegram_user() -> int:
    return 720_000_000 + new_id().int % 10_000_000


def rows(markup: Any) -> list[list[tuple[str, str | None]]]:
    """Кнопки по строкам: подпись и callback_data (у кнопок Mini App — None)."""
    assert isinstance(markup, InlineKeyboardMarkup)
    return [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]


def start_param(markup: Any, label: str) -> str:
    """Код deep link кнопки Mini App с подписью `label`."""
    assert isinstance(markup, InlineKeyboardMarkup)
    button = next(b for row in markup.inline_keyboard for b in row if b.text == label)
    assert button.web_app is not None
    return parse_qs(urlsplit(button.web_app.url).query)["startapp"][0]


def edited_markup(calls: list[TelegramMethod[Any]]) -> Any:
    edits = [call for call in calls if isinstance(call, EditMessageReplyMarkup)]
    assert len(edits) == 1, calls
    return edits[0].reply_markup


async def settings_of(harness: BotHarness, telegram_id: int) -> NotificationSettings:
    async with harness.container() as request:
        identity = await request.get(IdentityApi)
        user = await identity.by_telegram(telegram_id)
        assert user is not None
        query: NotificationQuery = await request.get(NotificationQuery)
        return await query.settings(user.id)


async def test_before_start_asks_to_press_start(harness: BotHarness) -> None:
    reply = await harness.send(telegram_user(), "/settings")

    assert reply.text == "Сначала нажмите /start — тогда здесь появятся настройки."
    assert reply.reply_markup is None


async def test_shows_language_groups_quiet_hours_and_app_links(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")

    reply = await harness.send(telegram_id, "/settings")

    assert reply.text is not None
    assert reply.text.startswith("<b>Настройки</b>\nЯзык — первой строкой.")
    assert rows(reply.reply_markup) == [
        LANGUAGES_RU,
        [("✅ Заявки по подпискам", "nset:job_matches")],
        [("✅ Отклики и выбор", "nset:responses")],
        [("✅ Сообщения", "nset:messages")],
        [("✅ Сделки, споры, отзывы", "nset:deals")],
        # новости — только по согласию: по умолчанию выключены
        [("▫️ Новости «Соседей»", "nset:marketing")],
        [("✅ Тихие часы 22:00–08:00", "nset:quiet")],
        [("Все настройки", None)],
        [("Удалить аккаунт", None)],
    ]
    assert start_param(reply.reply_markup, "Все настройки") == "m_settings"
    assert start_param(reply.reply_markup, "Удалить аккаунт") == "m_deletion"


async def test_group_switches_off_in_the_bot_only_and_back(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")
    await harness.send(telegram_id, "/settings")

    markup = edited_markup(await harness.press(telegram_id, "nset:messages"))

    assert [("▫️ Сообщения", "nset:messages")] in rows(markup)
    settings = await settings_of(harness, telegram_id)
    assert not settings.preferences.allows(EventGroup.MESSAGES, Channel.TELEGRAM)
    # в центре уведомлений (S42) группа остаётся: бот меняет только свой канал
    assert settings.preferences.allows(EventGroup.MESSAGES, Channel.IN_APP)

    markup = edited_markup(await harness.press(telegram_id, "nset:messages"))

    assert [("✅ Сообщения", "nset:messages")] in rows(markup)
    settings = await settings_of(harness, telegram_id)
    assert settings.preferences.allows(EventGroup.MESSAGES, Channel.TELEGRAM)


async def test_news_are_opt_in_and_quiet_hours_switch_off(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")

    await harness.press(telegram_id, "nset:marketing")
    markup = edited_markup(await harness.press(telegram_id, "nset:quiet"))

    assert [("✅ Новости «Соседей»", "nset:marketing")] in rows(markup)
    assert [("▫️ Тихие часы 22:00–08:00", "nset:quiet")] in rows(markup)
    settings = await settings_of(harness, telegram_id)
    assert settings.preferences.allows(EventGroup.MARKETING, Channel.TELEGRAM)
    assert not settings.quiet_hours.enabled
    # окно тихих часов не меняется: включить снова — те же 22:00–08:00
    assert settings.quiet_hours.start.hour == 22


async def test_double_press_toggles_twice(harness: BotHarness) -> None:
    """Апдейты нажатий бот обрабатывает параллельно: второе не теряется."""
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")

    await asyncio.gather(
        harness.press(telegram_id, "nset:deals"), harness.press(telegram_id, "nset:deals")
    )

    settings = await settings_of(harness, telegram_id)
    assert settings.preferences.allows(EventGroup.DEALS, Channel.TELEGRAM)


async def test_service_group_and_foreign_data_change_nothing(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")

    for data in ("nset:account", "nset:", "nset:quiet:extra"):
        calls = await harness.press(telegram_id, data)
        assert not any(isinstance(call, EditMessageReplyMarkup) for call in calls)

    assert await settings_of(harness, telegram_id) == NotificationSettings()


async def test_language_row_switches_the_bot_language(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")

    calls = await harness.press(telegram_id, "lang:sr-Cyrl")

    edits = [call for call in calls if isinstance(call, EditMessageText)]
    assert [edit.text for edit in edits] == ["Готово: језик — Српски (ћирилица)."]
    reply: SendMessage = await harness.send(telegram_id, "/settings")
    assert reply.text is not None
    assert reply.text.startswith("<b>Подешавања</b>")
    rendered = rows(reply.reply_markup)
    assert rendered[0] == [
        ("Русский", "lang:ru"),
        ("Srpski", "lang:sr-Latn"),
        ("✅ Српски", "lang:sr-Cyrl"),
    ]
    assert [("✅ Поруке", "nset:messages")] in rendered
