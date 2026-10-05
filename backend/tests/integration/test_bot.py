"""Бот: команды на фейковых Update (DEVELOPMENT_PLAN 0.22, 1.6, ADR-0011).

Bot API подменён сессией, которая записывает вызовы: сеть не нужна. БД и Valkey — настоящие
(testcontainers): /start создаёт пользователя тем же кодом, что и вход Mini App.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    WriteAccessAllowed,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from structlog.testing import capture_logs

from app.modules.growth.application.ports import RECORD_ATTRIBUTION
from app.modules.identity.api import IdentityApi
from app.modules.notifications.application.ports import GRANT_WRITE_ACCESS
from app.platform.kernel.errors import ConflictError
from app.platform.kernel.ids import new_id
from app.platform.kernel.localized import Locale
from app.platform.settings import Settings
from tests.plugins.bot import MINI_APP, BotHarness, bot_harness
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[3] / "packages" / "links" / "golden.json").read_text("utf-8")
)


@pytest.fixture
async def harness(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[BotHarness]:
    async with bot_harness(monkeypatch) as harness:
        yield harness


def telegram_user() -> int:
    return 700_000_000 + new_id().int % 10_000_000


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
    assert again.text.startswith("Dobro došli ponovo, Ana!")
    assert str(telegram_id) not in repr(logs)  # в логах только внутренний user_id


async def test_parallel_starts_of_one_user_all_get_welcome(harness: BotHarness) -> None:
    """Апдейты, накопившиеся, пока бот лежал, polling отдаёт разом, и aiogram обрабатывает их
    параллельно; двойное нажатие /start — тоже. Конфликт записи пользователя не должен
    доходить до человека сообщением об ошибке."""
    telegram_id = 700_000_000 + new_id().int % 10_000_000

    first = await harness.send_parallel(telegram_id, "/start", 5)  # новый пользователь
    again = await harness.send_parallel(telegram_id, "/start", 5)  # уже есть: запись входа

    texts = [*first, *again]
    assert all(text.startswith(("Здравствуйте, Ana!", "С возвращением, Ana!")) for text in texts), (
        texts
    )
    async with harness.container() as request:
        assert await (await request.get(IdentityApi)).by_telegram(telegram_id) is not None


async def test_start_in_russian_by_default(harness: BotHarness) -> None:
    reply = await harness.send(
        700_000_000 + new_id().int % 10_000_000, "/start", language="de", name="Иван"
    )
    assert reply.text.startswith("Здравствуйте, Иван!")


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


def _markup(reply: SendMessage) -> InlineKeyboardMarkup:
    assert isinstance(reply.reply_markup, InlineKeyboardMarkup)
    return reply.reply_markup


async def test_start_button_carries_the_same_startapp_code(harness: BotHarness) -> None:
    """Кнопка web_app открывает адрес как есть, поэтому код ссылки едет в `?startapp=`:
    для всех golden-векторов кодека — тот же код, для битых — адрес без кода."""
    telegram_id = telegram_user()
    for vector in GOLDEN["valid"]:
        reply = await harness.send(telegram_id, f"/start {vector['param']}")
        assert _button_url(reply) == f"{MINI_APP}?startapp={vector['param']}"
    for param in filter(None, GOLDEN["invalid"]):
        reply = await harness.send(telegram_id, f"/start {param}")
        assert _button_url(reply) == MINI_APP, param


async def test_names_are_escaped_in_html(harness: BotHarness) -> None:
    reply = await harness.send(telegram_user(), "/start", name="Ana & <b>Co</b>")

    assert reply.text.startswith("Здравствуйте, Ana &amp; &lt;b&gt;Co&lt;/b&gt;!")


async def test_app_opens_mini_app(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")

    reply = await harness.send(telegram_id, "/app")

    assert reply.text.startswith("Откройте «Соседи» кнопкой ниже")
    assert _button_url(reply) == MINI_APP


async def test_help_says_support_contact_comes_later_until_owner_gives_it(
    harness: BotHarness,
) -> None:
    reply = await harness.send(telegram_user(), "/help")

    assert "<b>Как это работает</b>" in reply.text
    assert "Не вносите предоплату незнакомым" in reply.text
    assert reply.text.endswith("Контакт поддержки скоро появится здесь.")
    assert reply.reply_markup is None


async def test_help_links_to_support_account(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with bot_harness(monkeypatch, TELEGRAM_SUPPORT_USERNAME="@sosedi_support") as harness:
        reply = await harness.send(telegram_user(), "/help", language="sr")

    assert reply.text.endswith("Pitanje ili problem? Pišite podršci — odgovorićemo.")
    button = _markup(reply).inline_keyboard[0][0]
    assert (button.text, button.url) == ("Piši podršci", "https://t.me/sosedi_support")


@pytest.mark.parametrize(
    ("command", "title", "label", "code"),
    [
        ("/terms", "Правила площадки «Соседи»", "Открыть правила", "l_terms"),
        ("/privacy", "Политика конфиденциальности", "Открыть политику", "l_privacy"),
    ],
)
async def test_legal_commands_open_the_s48_tab(
    harness: BotHarness, command: str, title: str, label: str, code: str
) -> None:
    reply = await harness.send(telegram_user(), command)

    assert reply.text.startswith(f"<b>{title}</b>\nРедакция 1 от 05.10.2026")
    button = _markup(reply).inline_keyboard[0][0]
    assert button.text == label
    assert button.web_app is not None
    assert button.web_app.url == f"{MINI_APP}?startapp={code}"


async def test_language_changes_ui_locale_and_answers_in_the_new_language(
    harness: BotHarness,
) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")

    prompt = await harness.send(telegram_id, "/language")
    options = [row[0] for row in _markup(prompt).inline_keyboard]
    calls = await harness.press(telegram_id, "lang:sr-Latn")

    assert prompt.text == "Выберите язык приложения и уведомлений:"
    assert [(o.text, o.callback_data) for o in options] == [
        ("Русский", "lang:ru"),
        ("Srpski (latinica)", "lang:sr-Latn"),
        ("Српски (ћирилица)", "lang:sr-Cyrl"),
    ]
    edits = [c for c in calls if isinstance(c, EditMessageText)]
    assert [e.text for e in edits] == ["Gotovo: jezik — Srpski (latinica)."]
    assert any(isinstance(c, AnswerCallbackQuery) for c in calls)
    async with harness.container() as request:
        user = await (await request.get(IdentityApi)).by_telegram(telegram_id)
    assert user is not None
    assert user.ui_locale is Locale.SR_LATN
    again = await harness.send(telegram_id, "/start")
    assert again.text.startswith("Dobro došli ponovo, Ana!")


async def test_foreign_language_callback_changes_nothing(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")

    calls = await harness.press(telegram_id, "lang:en")

    assert not [c for c in calls if isinstance(c, EditMessageText)]
    async with harness.container() as request:
        user = await (await request.get(IdentityApi)).by_telegram(telegram_id)
    assert user is not None
    assert user.ui_locale is Locale.RU


async def test_language_before_start_asks_to_press_start(harness: BotHarness) -> None:
    reply = await harness.send(telegram_user(), "/language")

    assert reply.text == "Сначала нажмите /start."


async def test_unknown_message_lists_commands(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")

    for text_value in ("привет", "/unknown"):
        reply = await harness.send(telegram_id, text_value)
        assert reply.text.startswith("Я понимаю команды:\n/app — открыть приложение")


async def test_production_bot_speaks_html(harness: BotHarness) -> None:
    """Bot из DI (platform/di.py) — с HTML по умолчанию: без него теги ушли бы текстом."""
    assert harness.bot.default.parse_mode == ParseMode.HTML
    reply = await harness.send(telegram_user(), "/help")
    assert "<b>" in reply.text


async def test_service_messages_get_no_reply(harness: BotHarness) -> None:
    """«Вы разрешили боту писать» после requestWriteAccess в Mini App — не повод для
    подсказки про команды: это первое сообщение в чате человека, не нажимавшего /start."""
    telegram_id = telegram_user()
    service = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=telegram_id, type="private"),
        write_access_allowed=WriteAccessAllowed(from_request=True),
    )

    assert await harness.feed(telegram_id, service) == []


async def test_legal_link_is_attributed_as_legal(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start l_terms")
    async with harness.container() as request:
        user = await (await request.get(IdentityApi)).by_telegram(telegram_id)
        engine = await request.get(AsyncEngine)
    assert user is not None

    assert await run_queued(harness.container, RECORD_ATTRIBUTION, user_id=user.id) == 1
    async with engine.connect() as conn:
        source = (
            await conn.execute(
                text("SELECT source FROM growth.attributions WHERE user_id = :user_id"),
                {"user_id": user.id},
            )
        ).scalar_one()
    assert source == "legal"


async def test_domain_error_on_button_is_answered_with_alert(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    boom = Router(name="test-boom")

    async def fail(_callback: CallbackQuery) -> None:
        raise ConflictError

    boom.callback_query.register(fail, F.data == "boom")
    async with bot_harness(monkeypatch, boom) as harness:
        calls = await harness.press(telegram_user(), "boom")

    answers = [c for c in calls if isinstance(c, AnswerCallbackQuery)]
    assert [(a.text, a.show_alert) for a in answers] == [
        ("Действие недоступно в текущем состоянии.", True)
    ]
