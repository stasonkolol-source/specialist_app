"""`cli notify-test` до вызова Bot API (DEVELOPMENT_PLAN 2.3b).

Уведомление `system.test` проходит весь конвейер — Notify, задача отправки (её здесь
выполняет «воркер» теста), лимитер в Valkey, адаптер aiogram — а Bot API записывается
(tests/plugins/bot.py). БД и Valkey настоящие.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._notify_test import run_notify_test
from app.modules.identity.api import IdentityApi
from app.modules.notifications.application.ports import GRANT_WRITE_ACCESS, SEND_DELIVERY
from app.platform.kernel.clock import SystemClock
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.tasks import TASKS, run_task
from app.platform.settings import Settings
from tests.plugins.bot import MINI_APP, BotHarness, bot_harness
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration


@pytest.fixture
async def harness(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[BotHarness]:
    async with bot_harness(monkeypatch) as harness:
        yield harness


def telegram_user() -> int:
    return 720_000_000 + new_id().int % 10_000_000


async def started(harness: BotHarness, telegram_id: int) -> UserId:
    """/start в боте и задача, которая открывает канал (как её выполнил бы воркер)."""
    await harness.send(telegram_id, "/start")
    async with harness.container() as request:
        identity: IdentityApi = await request.get(IdentityApi)
        user = await identity.by_telegram(telegram_id)
    assert user is not None
    await run_queued(harness.container, GRANT_WRITE_ACCESS, user_id=user.id)
    return user.id


async def worker_sends(harness: BotHarness, user_id: UserId, *, tries: int = 200) -> int:
    """Как воркер: взять задачу `notifications.send` доставки пользователя и выполнить."""
    spec = TASKS.tasks[SEND_DELIVERY.name]
    engine = await harness.container.get(AsyncEngine)
    for _ in range(tries):
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        "DELETE FROM procrastinate_jobs WHERE task_name = :name"
                        " AND status = 'todo' AND args->'payload'->>'delivery_id' IN ("
                        " SELECT d.id::text FROM notifications.deliveries d"
                        " JOIN notifications.notifications n ON n.id = d.notification_id"
                        " WHERE n.user_id = :user_id) RETURNING id, args"
                    ),
                    {"name": SEND_DELIVERY.name, "user_id": user_id},
                )
            ).all()
        for row in rows:
            await run_task(spec, harness.container, row.args["payload"], job_id=row.id)
        if rows:
            return len(rows)
        await asyncio.sleep(0.05)
    return 0


async def test_notify_test_reaches_the_bot_api(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    user_id = await started(harness, telegram_id)
    before = len(harness.session.calls)

    outcome, jobs = await asyncio.gather(
        run_notify_test(harness.container, str(telegram_id), wait=10),
        worker_sends(harness, user_id),  # воркер стенда
    )

    assert (outcome.sent, jobs) == (True, 1), outcome.message
    [call] = harness.session.calls[before:]
    assert isinstance(call, SendMessage)
    assert call.chat_id == telegram_id
    assert str(call.text).startswith("<b>Проверка уведомлений</b>")
    markup = call.reply_markup
    assert isinstance(markup, InlineKeyboardMarkup)
    web_app = markup.inline_keyboard[0][0].web_app
    assert web_app is not None
    assert web_app.url == f"{MINI_APP}?startapp=h"


async def test_notify_test_says_when_the_worker_is_silent(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    user_id = await started(harness, telegram_id)

    outcome = await run_notify_test(harness.container, str(telegram_id), wait=0.5)

    assert not outcome.sent
    assert "is the worker running" in outcome.message
    assert await worker_sends(harness, user_id) == 1  # задача ждала воркер: убрать за собой


async def test_notify_test_explains_why_it_could_not_send(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    user_id = await started(harness, telegram_id)
    await harness.member_status(
        telegram_id, blocked=True, at=SystemClock().now() + timedelta(seconds=2)
    )

    blocked = await run_notify_test(harness.container, str(user_id))  # по внутреннему id
    unknown = await run_notify_test(harness.container, "123")

    assert not blocked.sent
    assert "/start" in blocked.message
    assert (unknown.sent, unknown.message) == (False, "notify-test: no such user 123")
