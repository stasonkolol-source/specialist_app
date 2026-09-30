"""Статус канала следует за пользователем (DEVELOPMENT_PLAN 2.3b, ADR-0011).

Дату апдейта Telegram даёт в целых секундах: остановка в ту же секунду, что и /start, может
оказаться «раньше» него и канал не выключит — его выключит первый же ответ 403. Поэтому
даты остановок в тестах — явно позже /start.

«Готово, когда»: `my_chat_member` и /start возвращают канал; остановка и запуск бота
пользователем отражаются в `channels`. Бот — диспетчер процесса бота на фейковых Update,
Bot API записывается (tests/plugins/bot.py); БД и Valkey — настоящие, данные коммитятся.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.plugins.bot import BotHarness, bot_harness
from tests.plugins.queue import run_queued

from app.modules.identity.api import IdentityApi
from app.modules.notifications.application.ports import GRANT_WRITE_ACCESS
from app.platform.kernel.clock import SystemClock
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def harness(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[BotHarness]:
    async with bot_harness(monkeypatch) as harness:
        yield harness


def telegram_user() -> int:
    return 710_000_000 + new_id().int % 10_000_000


async def started(harness: BotHarness, telegram_id: int) -> UserId:
    """/start в боте и задача, которая открывает канал (как её выполнил бы воркер)."""
    await harness.send(telegram_id, "/start")
    async with harness.container() as request:
        identity: IdentityApi = await request.get(IdentityApi)
        user = await identity.by_telegram(telegram_id)
    assert user is not None
    await run_queued(harness.container, GRANT_WRITE_ACCESS, user_id=user.id)
    return user.id


async def channel(harness: BotHarness, user_id: UserId) -> dict[str, Any] | None:
    engine = await harness.container.get(AsyncEngine)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT granted_via, disabled_at FROM notifications.channels"
                    " WHERE user_id = :user_id"
                ),
                {"user_id": user_id},
            )
        ).one_or_none()
    return dict(row._mapping) if row is not None else None


async def test_channel_follows_the_user_stopping_and_starting_the_bot(
    harness: BotHarness,
) -> None:
    telegram_id = telegram_user()
    user_id = await started(harness, telegram_id)
    later = SystemClock().now() + timedelta(seconds=2)  # дата Telegram — до секунды

    calls = await harness.member_status(telegram_id, blocked=True, at=later)

    assert calls == []  # остановленному боту писать нечего и некуда
    stopped = await channel(harness, user_id)
    assert stopped is not None
    assert stopped["disabled_at"] is not None

    await harness.member_status(telegram_id, blocked=False, at=later + timedelta(seconds=3))

    assert await channel(harness, user_id) == {"granted_via": "bot_start", "disabled_at": None}


async def test_start_turns_a_stopped_channel_back_on(harness: BotHarness) -> None:
    telegram_id = telegram_user()
    user_id = await started(harness, telegram_id)
    stopped_at = SystemClock().now() + timedelta(seconds=1)  # дата Telegram — до секунды
    await harness.member_status(telegram_id, blocked=True, at=stopped_at)
    stopped = await channel(harness, user_id)
    assert stopped is not None
    # дата апдейта — целые секунды, aiogram округляет: сверяем с точностью до секунды
    assert abs(stopped["disabled_at"] - stopped_at) <= timedelta(seconds=1)
    await asyncio.sleep(2)  # /start нажат уже после остановки (с запасом на округление)

    await started(harness, telegram_id)

    reopened = await channel(harness, user_id)
    assert reopened is not None
    assert reopened["disabled_at"] is None


async def test_channel_status_of_a_stranger_changes_nothing(harness: BotHarness) -> None:
    telegram_id = telegram_user()  # /start не нажимал

    assert await harness.member_status(telegram_id, blocked=True) == []
