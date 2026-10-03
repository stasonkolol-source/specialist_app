"""Подписки на заявки в боте (DEVELOPMENT_PLAN 5.7, ARCHITECTURE §11.3) на фейковых Update.

Кнопки карточки B1: «Откликнуться шаблоном «…»» создаёт отклик тем же use case, что S16, «Не
интересно» скрывает заявку и оставляет у карточки только «Открыть заявку», «Пауза подписки» —
неделя тишины, кнопка становится «Снять паузу». `/alerts` — подписки строками и пауза всех;
`/feed` — заявки по подпискам кнопками в Mini App.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from aiogram.methods import EditMessageReplyMarkup, EditMessageText
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.kernel.ids import new_id
from app.platform.telegram.callbacks import CallbackAction, CallbackData, encode_callback, ref_arg
from app.platform.telegram.deeplinks import uuid_to_base62
from tests.integration.test_bot_jobs import (
    accept,
    alerts,
    app_buttons,
    app_url,
    execute,
    pressed,
    published_job,
    telegram_user,
    template_of,
)
from tests.plugins.bot import MINI_APP, BotHarness, bot_harness

pytestmark = pytest.mark.integration


@pytest.fixture
async def harness(
    monkeypatch: pytest.MonkeyPatch, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[BotHarness]:
    async with bot_harness(monkeypatch) as harness:
        yield harness


async def rows(harness: BotHarness, sql: str, **params: object) -> list[Any]:
    async with harness.container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def user_of(harness: BotHarness, telegram_id: int) -> UUID:
    [row] = await rows(
        harness,
        "SELECT user_id FROM identity.auth_identities WHERE provider = 'telegram'"
        " AND subject = :subject",
        subject=str(telegram_id),
    )
    return UUID(str(row.user_id))


async def alert_of(
    harness: BotHarness, telegram_id: int, *, delivery: str = "instant", paused: bool = False
) -> UUID:
    """Подписка пользователя бота на раздел заявок `published_job` — строкой."""
    alert_id = new_id()
    await execute(
        harness,
        "INSERT INTO jobs.alerts (id, user_id, category_ids, city_id, delivery, paused_until)"
        " SELECT :id, a.user_id, ARRAY[c.parent_id], ci.id, :delivery, :paused"
        " FROM identity.auth_identities a, geo.cities ci,"
        " (SELECT parent_id FROM catalog.categories WHERE id ="
        "  (SELECT min(id) FROM catalog.categories WHERE parent_id IS NOT NULL)) c"
        " WHERE a.provider = 'telegram' AND a.subject = :subject AND ci.slug = 'novi-sad'",
        id=alert_id,
        delivery=delivery,
        paused=datetime.now(UTC) + timedelta(days=1) if paused else None,
        subject=str(telegram_id),
    )
    return alert_id


def card(job_id: UUID, alert_id: UUID, template_id: UUID) -> InlineKeyboardMarkup:
    """Клавиатура карточки B1, как её рисует notifications."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть заявку",
                    web_app=WebAppInfo(url=app_url(f"j_{uuid_to_base62(job_id)}")),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Откликнуться шаблоном «Могу сегодня»",
                    callback_data=pressed(CallbackAction.JOB_RESPOND, job_id, ref_arg(template_id)),
                )
            ],
            [
                InlineKeyboardButton(
                    text="Не интересно", callback_data=pressed(CallbackAction.JOB_HIDE, job_id)
                ),
                InlineKeyboardButton(
                    text="Пауза подписки",
                    callback_data=pressed(CallbackAction.ALERT_PAUSE, alert_id),
                ),
            ],
        ]
    )


def markup_of(calls: list[Any]) -> list[list[str]]:
    [edit] = [call for call in calls if isinstance(call, EditMessageReplyMarkup)]
    assert isinstance(edit.reply_markup, InlineKeyboardMarkup)
    return [[button.text for button in row] for row in edit.reply_markup.inline_keyboard]


async def test_card_template_button_responds_like_s16(harness: BotHarness) -> None:
    client, performer = telegram_user(), telegram_user()
    for telegram_id in (client, performer):
        await harness.send(telegram_id, "/start")
    await accept(harness, performer)
    job_id = await published_job(harness, client)
    alert_id = await alert_of(harness, performer)
    template_id = await template_of(harness, performer)
    button = pressed(CallbackAction.JOB_RESPOND, job_id, ref_arg(template_id))

    calls = await harness.press(performer, button, markup=card(job_id, alert_id, template_id))

    assert alerts(calls) == [
        "Отклик отправлен шаблоном «Могу сегодня» — клиент увидит его после проверки."
    ]
    assert markup_of(calls) == [["Открыть заявку"], ["Не интересно", "Пауза подписки"]]
    [response] = await rows(
        harness, "SELECT template_id FROM jobs.responses WHERE job_id = :id", id=job_id
    )
    assert response.template_id == template_id


async def test_not_interested_hides_the_job(harness: BotHarness) -> None:
    client, performer = telegram_user(), telegram_user()
    for telegram_id in (client, performer):
        await harness.send(telegram_id, "/start")
    job_id = await published_job(harness, client)
    alert_id = await alert_of(harness, performer)

    calls = await harness.press(
        performer,
        pressed(CallbackAction.JOB_HIDE, job_id),
        markup=card(job_id, alert_id, new_id()),
    )

    assert alerts(calls) == ["Скрыли: эта заявка больше не появится в вашей ленте."]
    assert markup_of(calls) == [["Открыть заявку"]]
    user_id = await user_of(harness, performer)
    assert await rows(
        harness,
        "SELECT job_id FROM jobs.hidden_jobs WHERE user_id = :user AND job_id = :job",
        user=user_id,
        job=job_id,
    )


async def test_pause_button_pauses_this_alert_for_a_week_and_back(harness: BotHarness) -> None:
    client, performer = telegram_user(), telegram_user()
    for telegram_id in (client, performer):
        await harness.send(telegram_id, "/start")
    job_id = await published_job(harness, client)
    alert_id = await alert_of(harness, performer)
    other = await alert_of(harness, performer)
    markup = card(job_id, alert_id, new_id())

    paused = await harness.press(
        performer, pressed(CallbackAction.ALERT_PAUSE, alert_id), markup=markup
    )

    [toast] = alerts(paused)
    assert toast is not None
    assert toast.startswith("Подписка «Мастер на час» на паузе до ")
    assert markup_of(paused)[-1] == ["Не интересно", "Снять паузу"]
    states = {
        row.id: row.paused_until
        for row in await rows(
            harness,
            "SELECT id, paused_until FROM jobs.alerts WHERE id IN (:a, :b)",
            a=alert_id,
            b=other,
        )
    }
    assert states[other] is None  # пауза — только этой подписки
    assert states[alert_id] > datetime.now(UTC) + timedelta(days=6)

    resumed = await harness.press(performer, pressed(CallbackAction.ALERT_RESUME, alert_id))
    [toast] = alerts(resumed)
    assert toast is not None
    assert toast.endswith("снова присылает заявки.")
    [row] = await rows(harness, "SELECT paused_until FROM jobs.alerts WHERE id = :id", id=alert_id)
    assert row.paused_until is None


async def test_someone_elses_alert_cannot_be_paused(harness: BotHarness) -> None:
    owner, stranger = telegram_user(), telegram_user()
    for telegram_id in (owner, stranger):
        await harness.send(telegram_id, "/start")
    alert_id = await alert_of(harness, owner)

    calls = await harness.press(stranger, pressed(CallbackAction.ALERT_PAUSE, alert_id))

    assert alerts(calls) == ["Подписка не найдена: её удалили."]


async def test_alerts_command_lists_and_pauses_all(harness: BotHarness) -> None:
    performer = telegram_user()
    await harness.send(performer, "/start")
    empty = await harness.send(performer, "/alerts")
    assert empty.text is not None
    assert empty.text.startswith("<b>Подписок пока нет</b>")
    assert app_buttons(empty) == [[("Настроить подписки", app_url("m_alerts"))]]

    await alert_of(harness, performer)
    await alert_of(harness, performer, delivery="digest", paused=True)
    listed = await harness.send(performer, "/alerts")

    assert listed.text is not None
    lines = listed.text.splitlines()
    assert lines[0] == "<b>Подписки на заявки</b>"
    assert lines[2].startswith("• <b>Мастер на час</b> — сразу · за неделю: ")
    assert "на паузе до" in lines[3]
    markup = listed.reply_markup
    assert isinstance(markup, InlineKeyboardMarkup)
    labels = [[button.text for button in row] for row in markup.inline_keyboard]
    assert labels == [
        ["Пауза на сегодня", "Пауза на неделю", "Снять паузу"],
        ["Настроить подписки"],
    ]
    week = markup.inline_keyboard[0][1].callback_data
    assert week is not None

    calls = await harness.press(performer, week)

    assert alerts(calls) == ["Подписки на паузе на неделю."]
    [edit] = [call for call in calls if isinstance(call, EditMessageText)]
    assert edit.text is not None
    assert edit.text.count("на паузе до") == 2
    user_id = await user_of(harness, performer)
    paused = await rows(
        harness,
        "SELECT paused_until FROM jobs.alerts WHERE user_id = :id AND paused_until IS NOT NULL",
        id=user_id,
    )
    assert len(paused) == 2
    stranger = telegram_user()
    await harness.send(stranger, "/start")
    foreign = await harness.press(stranger, week)  # чужая кнопка — без действия
    assert alerts(foreign) == [None]


async def test_feed_command_lists_jobs_by_alerts(harness: BotHarness) -> None:
    client, performer = telegram_user(), telegram_user()
    for telegram_id in (client, performer):
        await harness.send(telegram_id, "/start")
    none = await harness.send(performer, "/feed")
    assert none.text is not None
    assert none.text.startswith("<b>Подписок пока нет</b>")
    job_id = await published_job(harness, client, title="Собрать <шкаф>")
    await execute(  # путь услуги — с разделом, как у заявок из мастера S20
        harness,
        "UPDATE jobs.jobs SET category_path = c.path FROM catalog.categories c"
        " WHERE jobs.jobs.id = :id AND c.id = jobs.jobs.category_id",
        id=job_id,
    )
    await alert_of(harness, performer)

    reply = await harness.send(performer, "/feed")

    assert reply.text is not None
    assert reply.text.startswith("<b>Заявки по подпискам</b>\n\n")
    assert "• <b>Собрать &lt;шкаф&gt;</b> — договорная" in reply.text
    buttons = app_buttons(reply)
    assert [("Собрать <шкаф>", app_url(f"j_{uuid_to_base62(job_id)}"))] in buttons
    assert buttons[-1] == [("Открыть ленту", app_url("m_feed"))]
    assert MINI_APP in buttons[-1][0][1]


async def test_alert_buttons_without_an_account_do_nothing(harness: BotHarness) -> None:
    stranger = telegram_user()
    data = encode_callback(CallbackData(CallbackAction.ALERT_PAUSE, new_id()))

    calls = await harness.press(stranger, data)

    assert alerts(calls) == [None]
    assert (await harness.send(stranger, "/alerts")).text == "Сначала нажмите /start."
    assert (await harness.send(stranger, "/feed")).text == "Сначала нажмите /start."
