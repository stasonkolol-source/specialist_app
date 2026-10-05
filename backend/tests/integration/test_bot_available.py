"""/available в боте (DEVELOPMENT_PLAN 2.10): «Доступен сегодня» из чата — те же варианты и тот же
use case, что у S38. Варианты зависят от часа по Белграду: проверяем те, что ещё впереди."""

from collections.abc import AsyncIterator

import pytest
from aiogram.methods import EditMessageText, SendMessage
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.platform.kernel.clock import BUSINESS_TZ, Clock
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.bot import BotHarness, bot_harness
from tests.plugins.identity import accept_rules

pytestmark = pytest.mark.integration


@pytest.fixture
async def harness(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, geo_seeded: None
) -> AsyncIterator[BotHarness]:
    """Бот со справочником городов: профилю нужен город (Нови-Сад из сидов)."""
    async with bot_harness(monkeypatch) as harness:
        yield harness


def telegram_user() -> int:
    return 7_000_000_000 + new_id().int % 1_000_000_000


async def publish_profile(harness: BotHarness, telegram_id: int) -> None:
    """Опубликованный профиль пользователя — SQL-вставкой: модерация этому тесту не нужна.
    Правила приняты, как у любого, кто создал профиль: «доступен сегодня» без галочки S02c и
    при санкции на публикацию недоступен (SEC-01)."""
    async with harness.container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.begin() as conn:
        user_id: UserId = (
            await conn.execute(
                text(
                    "SELECT user_id FROM identity.auth_identities"
                    " WHERE provider = 'telegram' AND subject = :subject"
                ),
                {"subject": str(telegram_id)},
            )
        ).scalar_one()
    async with harness.container() as request:
        await accept_rules(await request.get(AsyncSession), user_id)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO specialists.profiles"
                " (id, user_id, kind, status, display_name, city_id, created_at, version)"
                " SELECT :id, a.user_id, 'pro', 'published', 'Ana', c.id, now(), 1"
                " FROM identity.auth_identities a, geo.cities c"
                " WHERE a.provider = 'telegram' AND a.subject = :subject AND c.slug = 'novi-sad'"
            ),
            {"id": new_id(), "subject": str(telegram_id)},
        )


def buttons(reply: SendMessage) -> list[tuple[str, str | None]]:
    markup = reply.reply_markup
    assert isinstance(markup, InlineKeyboardMarkup)
    return [(b.text, b.callback_data) for row in markup.inline_keyboard for b in row]


async def test_without_a_published_profile_points_to_the_app(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")

    reply = await harness.send(telegram_id, "/available")

    assert reply.text is not None
    assert reply.text.startswith("«Доступен сегодня» — для опубликованного профиля специалиста")


async def test_switches_on_until_an_hour_and_off_again(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")
    await publish_profile(harness, telegram_id)
    async with harness.container() as request:
        now = (await request.get(Clock)).now()
    if now.astimezone(BUSINESS_TZ).hour >= 22:
        pytest.skip("после 22:00 по Белграду вариантов на сегодня нет")

    menu = await harness.send(telegram_id, "/available")
    assert menu.text is not None
    assert menu.text.startswith("«Доступен сегодня» выключено")
    assert ("до 22:00", "avail:22") in buttons(menu)

    calls = await harness.press(telegram_id, "avail:22")
    edits = [call for call in calls if isinstance(call, EditMessageText)]
    assert [edit.text for edit in edits] == ["Готово: вы доступны сегодня до 22:00."]

    again = await harness.send(telegram_id, "/available")
    assert again.text == "Вы «доступны сегодня» до 22:00. Поменять время или выключить:"
    assert ("Выключить", "avail:off") in buttons(again)
    calls = await harness.press(telegram_id, "avail:off")
    edits = [call for call in calls if isinstance(call, EditMessageText)]
    assert [edit.text for edit in edits] == ["Готово: «доступен сегодня» выключено."]
