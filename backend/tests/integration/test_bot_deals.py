"""Кнопки сделки в боте (DEVELOPMENT_PLAN 6.1b, 6.3b; ARCHITECTURE §11.3): «Да, выполнено» под
«Работа выполнена?» вызывает тот же CompleteDeal, что S26: отметка стороны, вторая отметка
завершает сделку. «Подтвердить» и «Отклонить» под «Договорились?» — те же ConfirmDeal и
DeclineDeal, что S53. Повтор нажатия ничего не меняет, чужая сделка — «не найдена»."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, TelegramMethod
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from app.platform.telegram.callbacks import CallbackAction, CallbackData, encode_callback
from tests.plugins.bot import BotHarness, bot_harness

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


async def agreed_deal(harness: BotHarness, client: int, performer: int) -> UUID:
    """Идущая сделка двух пользователей бота — строкой: выбор отклика тесту не нужен."""
    deal_id = new_id()
    await sql(
        harness,
        "INSERT INTO deals.deals (id, client_id, performer_id, origin, title_snapshot, status,"
        " agreed_at, version) SELECT :id, c.user_id, p.user_id, 'direct', 'Повесить люстру',"
        " 'agreed', now(), 1 FROM identity.auth_identities c, identity.auth_identities p"
        " WHERE c.provider = 'telegram' AND c.subject = :client"
        " AND p.provider = 'telegram' AND p.subject = :performer",
        id=deal_id,
        client=str(client),
        performer=str(performer),
    )
    return deal_id


async def proposed_deal(harness: BotHarness, client: int, performer: int) -> UUID:
    """«Договорились» исполнителя в чате — строкой: ждёт ответа клиента."""
    deal_id = new_id()
    await sql(
        harness,
        "INSERT INTO deals.deals (id, client_id, performer_id, origin, title_snapshot, status,"
        " proposed_by, version) SELECT :id, c.user_id, p.user_id, 'chat', 'Повесить люстру',"
        " 'proposed', p.user_id, 1 FROM identity.auth_identities c, identity.auth_identities p"
        " WHERE c.provider = 'telegram' AND c.subject = :client"
        " AND p.provider = 'telegram' AND p.subject = :performer",
        id=deal_id,
        client=str(client),
        performer=str(performer),
    )
    return deal_id


def edits(calls: list[TelegramMethod[Any]]) -> list[str | None]:
    return [call.text for call in calls if isinstance(call, EditMessageText)]


def alerts(calls: list[TelegramMethod[Any]]) -> list[str | None]:
    return [call.text for call in calls if isinstance(call, AnswerCallbackQuery)]


async def test_yes_marks_then_completes_and_repeats_quietly(harness: BotHarness) -> None:
    client, performer, stranger = telegram_user(), telegram_user(), telegram_user()
    for telegram_id in (client, performer, stranger):
        await harness.send(telegram_id, "/start")
    deal_id = await agreed_deal(harness, client, performer)
    yes = encode_callback(CallbackData(CallbackAction.DEAL_COMPLETE, deal_id))

    first = await harness.press(client, yes)
    again = await harness.press(client, yes)
    second = await harness.press(performer, yes)
    late = await harness.press(client, yes)
    foreign = await harness.press(stranger, yes)

    marked = (
        "Отмечено: работа выполнена. Сделка завершится, когда подтвердит вторая сторона, — или"
        " сама через 3 дня."
    )
    assert edits(first) == [marked]
    assert edits(again) in ([marked], [])  # тот же текст Telegram может отвергнуть
    assert edits(second) == ["Сделка завершена. Спасибо!"]
    assert edits(late) in (["Сделка завершена. Спасибо!"], [])
    assert edits(foreign) == []
    assert alerts(foreign) == ["Сделка не найдена."]
    row = await sql(harness, "SELECT status FROM deals.deals WHERE id = :id", id=deal_id)
    assert row.status == "completed"


async def test_confirm_and_decline_answer_the_proposal(harness: BotHarness) -> None:
    client, performer, stranger = telegram_user(), telegram_user(), telegram_user()
    for telegram_id in (client, performer, stranger):
        await harness.send(telegram_id, "/start")
    confirmed_id = await proposed_deal(harness, client, performer)
    declined_id = await proposed_deal(harness, client, performer)

    def button(action: CallbackAction, deal_id: UUID) -> str:
        return encode_callback(CallbackData(action, deal_id))

    foreign = await harness.press(stranger, button(CallbackAction.DEAL_CONFIRM, confirmed_id))
    confirmed = await harness.press(client, button(CallbackAction.DEAL_CONFIRM, confirmed_id))
    too_late = await harness.press(client, button(CallbackAction.DEAL_DECLINE, confirmed_id))
    declined = await harness.press(client, button(CallbackAction.DEAL_DECLINE, declined_id))
    again = await harness.press(client, button(CallbackAction.DEAL_DECLINE, declined_id))

    closed = "Предложение уже неактуально: его подтвердили, отклонили или срок истёк."
    assert alerts(foreign) == ["Сделка не найдена."]
    assert edits(confirmed) == [
        "Договорились! Сделка в силе — в чате теперь можно поделиться контактом."
    ]
    assert edits(too_late) == [closed]  # подтверждённую так не отменить
    assert edits(declined) == ["Предложение отклонено."]
    assert edits(again) in (["Предложение отклонено."], [])
    statuses = [
        (await sql(harness, "SELECT status, cancel_reason FROM deals.deals WHERE id = :id", id=i))
        for i in (confirmed_id, declined_id)
    ]
    assert [tuple(row) for row in statuses] == [("agreed", None), ("cancelled", "no_agreement")]
