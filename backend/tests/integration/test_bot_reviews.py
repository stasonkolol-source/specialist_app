"""Звёзды под «Оцените работу» в боте (DEVELOPMENT_PLAN 7.3, B2; ARCHITECTURE §11.3): нажатие —
тот же LeaveReview, что S27: отзыв с одной оценкой уходит на проверку; второй раз — «уже
оставили», через 14 дней — «срок вышел», чужая сделка — «не найдена»."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, TelegramMethod
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from app.platform.telegram.callbacks import CallbackAction, CallbackData, encode_callback
from tests.plugins.bot import BotHarness, bot_harness
from tests.plugins.identity import accept_rules

pytestmark = pytest.mark.integration


@pytest.fixture
async def harness(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[BotHarness]:
    """Бот на тестовой БД (`settings` поднимает контейнеры и переменные окружения)."""
    async with bot_harness(monkeypatch) as harness:
        yield harness


def telegram_user() -> int:
    return 7_000_000_000 + new_id().int % 1_000_000_000


async def sql(harness: BotHarness, statement: str, **params: object) -> Any:
    async with harness.container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.begin() as conn:
        result = await conn.execute(text(statement), params)
        return result.first() if result.returns_rows else None


async def member(harness: BotHarness) -> int:
    """Пользователь бота, принявший правила (иначе отзыв не оставить)."""
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")
    row = await sql(
        harness,
        "SELECT user_id FROM identity.auth_identities WHERE provider = 'telegram'"
        " AND subject = :subject",
        subject=str(telegram_id),
    )
    async with harness.container() as request:
        await accept_rules(await request.get(AsyncSession), UserId(row.user_id))
    return telegram_id


async def completed_deal(harness: BotHarness, client: int, performer: int, ago: str) -> UUID:
    """Завершённая сделка двух пользователей бота — строкой."""
    deal_id = new_id()
    await sql(
        harness,
        "INSERT INTO deals.deals (id, client_id, performer_id, origin, title_snapshot, status,"
        " agreed_at, completed_at, version) SELECT :id, c.user_id, p.user_id, 'direct',"
        " 'Повесить люстру', 'completed', now() - CAST(:ago AS interval),"
        " now() - CAST(:ago AS interval), 1 FROM identity.auth_identities c,"
        " identity.auth_identities p WHERE c.provider = 'telegram' AND c.subject = :client"
        " AND p.provider = 'telegram' AND p.subject = :performer",
        id=deal_id,
        client=str(client),
        performer=str(performer),
        ago=ago,
    )
    return deal_id


def star(deal_id: UUID, rating: int) -> str:
    return encode_callback(CallbackData(CallbackAction.REVIEW_RATE, deal_id, str(rating)))


def edits(calls: list[TelegramMethod[Any]]) -> list[str | None]:
    return [call.text for call in calls if isinstance(call, EditMessageText)]


def alerts(calls: list[TelegramMethod[Any]]) -> list[str | None]:
    return [call.text for call in calls if isinstance(call, AnswerCallbackQuery)]


async def test_star_leaves_a_rating_once(harness: BotHarness) -> None:
    client = await member(harness)
    performer = await member(harness)
    stranger = await member(harness)
    deal_id = await completed_deal(harness, client, performer, "1 hour")

    rated = await harness.press(client, star(deal_id, 4))
    again = await harness.press(client, star(deal_id, 5))
    foreign = await harness.press(stranger, star(deal_id, 5))

    assert edits(rated) == [
        "Спасибо! Ваша оценка: ★★★★☆. Отзыв появится на карточке исполнителя после проверки."
    ]
    assert edits(again) == ["Вы уже оставили отзыв по этой сделке."]
    assert edits(foreign) == []
    assert alerts(foreign) == ["Сделка не найдена."]
    row = await sql(
        harness, "SELECT rating, status, body FROM reviews.reviews WHERE deal_id = :id", id=deal_id
    )
    assert (row.rating, row.status, row.body) == (4, "under_review", None)


async def test_star_after_the_window_says_it_is_too_late(harness: BotHarness) -> None:
    client, performer = await member(harness), await member(harness)
    deal_id = await completed_deal(harness, client, performer, "15 days")

    late = await harness.press(client, star(deal_id, 5))

    assert edits(late) == [
        "Срок вышел: отзыв можно оставить в течение 14 дней после завершения сделки."
    ]
    row = await sql(
        harness, "SELECT count(*) AS n FROM reviews.reviews WHERE deal_id = :id", id=deal_id
    )
    assert row.n == 0
