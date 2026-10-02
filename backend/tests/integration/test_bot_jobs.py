"""Заявки в боте (DEVELOPMENT_PLAN 5.1, 5.6, ARCHITECTURE §11.3): кнопки уведомлений и команды.

«Продлить» и «Закрыть» на фейковых Update вызывают те же use cases, что Mini App. Чужая заявка —
«не найдена», четвёртое продление — отказ с числом продлений. «Откликнуться: «…»» из приглашения
создаёт отклик из шаблона, повтор — «уже откликались». `/new` — кнопка мастера S20a, `/jobs` —
активные заявки с состоянием и кнопками в Mini App."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.platform.kernel.ids import UserId, new_id
from app.platform.telegram.callbacks import (
    CallbackAction,
    CallbackData,
    encode_callback,
    ref_arg,
)
from app.platform.telegram.deeplinks import uuid_to_base62
from tests.plugins.bot import MINI_APP, BotHarness, bot_harness
from tests.plugins.identity import accept_rules

pytestmark = pytest.mark.integration

TITLE = "Повесить люстру"


@pytest.fixture
async def harness(
    monkeypatch: pytest.MonkeyPatch, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[BotHarness]:
    async with bot_harness(monkeypatch) as harness:
        yield harness


def telegram_user() -> int:
    return 7_000_000_000 + new_id().int % 1_000_000_000


async def execute(harness: BotHarness, sql: str, **params: object) -> None:
    async with harness.container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


async def published_job(
    harness: BotHarness,
    telegram_id: int,
    *,
    extensions: int = 0,
    title: str = TITLE,
    status: str = "published",
) -> UUID:
    """Заявка пользователя бота (по умолчанию опубликованная) — SQL-вставкой: модерация тесту
    не нужна."""
    job_id = new_id()
    await execute(
        harness,
        "INSERT INTO jobs.jobs (id, client_id, status, title, description, content_lang,"
        " category_id, category_path, urgency, budget_type, city_id, extensions_count,"
        " published_at, expires_at, version)"
        " SELECT :id, a.user_id, :status, :title, '', 'ru', c.id, ARRAY[c.id], 'this_week',"
        " 'negotiable', ci.id, :extensions, now(), now() + interval '1 hour', 1"
        " FROM identity.auth_identities a, geo.cities ci,"
        " (SELECT min(id) AS id FROM catalog.categories WHERE parent_id IS NOT NULL) c"
        " WHERE a.provider = 'telegram' AND a.subject = :subject AND ci.slug = 'novi-sad'",
        id=job_id,
        title=title,
        status=status,
        extensions=extensions,
        subject=str(telegram_id),
    )
    return job_id


async def job_row(harness: BotHarness, job_id: UUID) -> Any:
    async with harness.container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.connect() as conn:
        sql = "SELECT status, close_reason, extensions_count, expires_at FROM jobs.jobs"
        return (await conn.execute(text(f"{sql} WHERE id = :id"), {"id": job_id})).one()


def pressed(action: CallbackAction, job_id: UUID, arg: str | None = None) -> str:
    return encode_callback(CallbackData(action, job_id, arg))


def edits(calls: list[TelegramMethod[Any]]) -> list[EditMessageText]:
    return [call for call in calls if isinstance(call, EditMessageText)]


def alerts(calls: list[TelegramMethod[Any]]) -> list[str | None]:
    return [call.text for call in calls if isinstance(call, AnswerCallbackQuery)]


def keyboard(edit: EditMessageText) -> list[str]:
    markup = edit.reply_markup
    assert isinstance(markup, InlineKeyboardMarkup)
    return [button.text for row in markup.inline_keyboard for button in row]


async def test_extend_button_extends_the_job(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")
    job_id = await published_job(harness, telegram_id)
    before = await job_row(harness, job_id)

    calls = await harness.press(telegram_id, pressed(CallbackAction.JOB_EXTEND, job_id))

    [edit] = edits(calls)
    assert edit.text is not None
    assert edit.text.startswith(f"Заявка «{TITLE}» продлена до ")
    after = await job_row(harness, job_id)
    assert (after.status, after.extensions_count) == ("published", 1)
    assert after.expires_at == before.expires_at + timedelta(days=7)  # ещё неделя к сроку


async def test_close_asks_the_reason_then_closes(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")
    job_id = await published_job(harness, telegram_id)

    [question] = edits(await harness.press(telegram_id, pressed(CallbackAction.JOB_CLOSE, job_id)))
    [found] = edits(
        await harness.press(telegram_id, pressed(CallbackAction.JOB_CLOSE, job_id, "found"))
    )
    closing = pressed(CallbackAction.JOB_CLOSE, job_id, "hired_elsewhere")
    [closed] = edits(await harness.press(telegram_id, closing))

    assert question.text == f"Почему закрываете заявку «{TITLE}»?"
    assert keyboard(question) == [
        "Нашёлся здесь, в «Соседях»",
        "Нашёлся в другом месте",
        "Уже не нужно",
        "Никто не подошёл",
        "Продлить",  # передумали закрывать
    ]
    assert found.text == f"Где нашёлся исполнитель для заявки «{TITLE}»?"
    assert keyboard(found) == ["Нашёлся здесь, в «Соседях»", "Нашёлся в другом месте", "Продлить"]
    assert closed.text == f"Заявка «{TITLE}» закрыта."
    row = await job_row(harness, job_id)
    assert (row.status, row.close_reason) == ("closed", "hired_elsewhere")
    again = await harness.press(telegram_id, pressed(CallbackAction.JOB_CLOSE, job_id))
    assert edits(again) == []  # закрытую не спрашиваем о причине
    assert alerts(again) == ["С заявкой в этом статусе так нельзя."]


async def test_strangers_job_is_not_found_and_stays_as_is(harness: BotHarness) -> None:
    owner, stranger = telegram_user(), telegram_user()
    await harness.send(owner, "/start")
    await harness.send(stranger, "/start")
    job_id = await published_job(harness, owner)

    for data in (
        pressed(CallbackAction.JOB_EXTEND, job_id),
        pressed(CallbackAction.JOB_CLOSE, job_id),
        pressed(CallbackAction.JOB_CLOSE, job_id, "not_needed"),
    ):
        calls = await harness.press(stranger, data)
        assert edits(calls) == []
        assert alerts(calls) == ["Заявка не найдена: её удалили или она вам не видна."]
    row = await job_row(harness, job_id)
    assert (row.status, row.extensions_count) == ("published", 0)


async def test_fourth_extension_is_refused_with_the_count(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")
    job_id = await published_job(harness, telegram_id, extensions=3)

    calls = await harness.press(telegram_id, pressed(CallbackAction.JOB_EXTEND, job_id))

    assert edits(calls) == []
    assert alerts(calls) == ["Заявку уже продлевали 3 раза — больше нельзя. Создайте новую."]


async def test_button_of_someone_without_an_account_is_ignored(harness: BotHarness) -> None:
    calls = await harness.press(telegram_user(), pressed(CallbackAction.JOB_EXTEND, new_id()))

    assert edits(calls) == []
    assert alerts(calls) == [None]


async def accept(harness: BotHarness, telegram_id: int) -> None:
    async with harness.container() as request:
        engine = await request.get(AsyncEngine)
        async with engine.connect() as conn:
            user_id = (
                await conn.execute(
                    text(
                        "SELECT user_id FROM identity.auth_identities"
                        " WHERE provider = 'telegram' AND subject = :subject"
                    ),
                    {"subject": str(telegram_id)},
                )
            ).scalar_one()
        await accept_rules(await request.get(AsyncSession), UserId(user_id))


async def template_of(harness: BotHarness, telegram_id: int) -> UUID:
    """Шаблон отклика пользователя бота — строкой."""
    template_id = new_id()
    await execute(
        harness,
        "INSERT INTO jobs.response_templates (id, user_id, title, message, price_type,"
        " price_amount, availability_note, position) SELECT :id, a.user_id, 'Могу сегодня',"
        " 'Здравствуйте! Могу сегодня вечером.', 'fixed', 300000, 'сегодня', 0"
        " FROM identity.auth_identities a WHERE a.provider = 'telegram' AND a.subject = :subject",
        id=template_id,
        subject=str(telegram_id),
    )
    return template_id


async def test_template_button_responds_once(harness: BotHarness) -> None:
    client, performer = telegram_user(), telegram_user()
    for telegram_id in (client, performer):
        await harness.send(telegram_id, "/start")
    await accept(harness, performer)  # отклик — создающее действие: правила приняты
    job_id = await published_job(harness, client)
    template_id = await template_of(harness, performer)
    button = pressed(CallbackAction.JOB_RESPOND, job_id, ref_arg(template_id))

    first = await harness.press(performer, button)
    again = await harness.press(performer, button)

    assert alerts(first) == [
        "Отклик отправлен шаблоном «Могу сегодня» — клиент увидит его после проверки."
    ]
    assert alerts(again) == ["Вы уже откликались на эту заявку."]
    async with harness.container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT template_id, message FROM jobs.responses WHERE job_id = :id"),
                {"id": job_id},
            )
        ).all()
    assert [(row.template_id, row.message) for row in rows] == [
        (template_id, "Здравствуйте! Могу сегодня вечером.")
    ]


def app_buttons(reply: SendMessage) -> list[list[tuple[str, str]]]:
    """Кнопки web_app под ответом: подпись и адрес Mini App."""
    markup = reply.reply_markup
    assert isinstance(markup, InlineKeyboardMarkup)
    return [
        [(button.text, button.web_app.url if button.web_app else "") for button in row]
        for row in markup.inline_keyboard
    ]


def app_url(code: str) -> str:
    return f"{MINI_APP}?startapp={code}"


async def test_new_opens_the_job_wizard(harness: BotHarness) -> None:
    reply = await harness.send(telegram_user(), "/new")  # и без аккаунта: Mini App его заведёт

    assert reply.text is not None
    assert reply.text.startswith("<b>Новая заявка</b>\nОпишите, что нужно сделать")
    assert app_buttons(reply) == [[("Создать заявку", app_url("n"))]]


async def test_jobs_needs_an_account(harness: BotHarness) -> None:
    reply = await harness.send(telegram_user(), "/jobs")

    assert reply.text == "Сначала нажмите /start."


async def test_jobs_without_active_jobs_offers_a_new_one(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")

    empty = await harness.send(telegram_id, "/jobs")
    await published_job(harness, telegram_id, status="closed")
    closed_only = await harness.send(telegram_id, "/jobs")

    assert empty.text is not None
    assert empty.text.startswith("Активных заявок нет.")
    assert app_buttons(empty) == [[("Создать заявку", app_url("n"))]]
    # закрытые — в «Моих заявках» S22
    assert closed_only.text == empty.text
    assert app_buttons(closed_only) == [
        [("Создать заявку", app_url("n"))],
        [("Все мои заявки", app_url("m_jobs"))],
    ]


async def test_jobs_lists_active_jobs_with_their_state(harness: BotHarness) -> None:
    client, performer = telegram_user(), telegram_user()
    for telegram_id in (client, performer):
        await harness.send(telegram_id, "/start")
    await accept(harness, performer)
    await published_job(harness, client, title="Старая", status="expired")
    long_title = "Собрать шкаф-купе из ИКЕА в спальне, три двери и зеркала"
    rejected = await published_job(harness, client, title=long_title, status="rejected")
    pending = await published_job(
        harness, client, title="Покрасить стену", status="pending_moderation"
    )
    waiting = await published_job(harness, client, title="Помыть окна")
    answered = await published_job(harness, client)
    template_id = await template_of(harness, performer)
    await harness.press(
        performer, pressed(CallbackAction.JOB_RESPOND, answered, ref_arg(template_id))
    )

    before_review = await harness.send(client, "/jobs")
    await execute(
        harness, "UPDATE jobs.responses SET review = 'clear' WHERE job_id = :id", id=answered
    )
    after_review = await harness.send(client, "/jobs")

    assert before_review.text == (
        "<b>Активные заявки</b>\n\n"
        f"• <b>{TITLE}</b> — откликов: 1 из 5\n"
        "• <b>Помыть окна</b> — ждём откликов\n"
        "• <b>Покрасить стену</b> — на проверке\n"
        f"• <b>{long_title}</b> — нужно исправить"
    )
    assert after_review.text is not None
    assert f"• <b>{TITLE}</b> — откликов: 1 из 5, новых: 1\n" in after_review.text
    # заявка открывается кнопкой `j_` (владельца S15 ведёт в S23), длинное название обрезано
    assert app_buttons(after_review) == [
        [(TITLE, app_url(f"j_{uuid_to_base62(answered)}"))],
        [("Помыть окна", app_url(f"j_{uuid_to_base62(waiting)}"))],
        [("Покрасить стену", app_url(f"j_{uuid_to_base62(pending)}"))],
        [("Собрать шкаф-купе из ИКЕА в спальне, тр…", app_url(f"j_{uuid_to_base62(rejected)}"))],
        [("Все мои заявки", app_url("m_jobs")), ("Новая заявка", app_url("n"))],
    ]


async def test_jobs_escapes_titles(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    await harness.send(telegram_id, "/start")
    await published_job(harness, telegram_id, title="Кран <b>течёт</b> & капает")

    reply = await harness.send(telegram_id, "/jobs")

    assert reply.text is not None
    assert "• <b>Кран &lt;b&gt;течёт&lt;/b&gt; &amp; капает</b> — ждём откликов" in reply.text
