"""Канал telegram на PostgreSQL: разрешение писать и подписчик BotStarted (1.4b)."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter
from sqlalchemy import text

from app.modules.notifications.application.ports import GRANT_WRITE_ACCESS
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccessCommand,
)
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.errors import TelegramNotLinkedError
from app.modules.notifications.tasks import grant_write_access
from app.platform.contracts.events.identity import BotStarted
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.tasks import TASKS

from .conftest import Notifications

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def granted(
    user_id: UserId, via: GrantedVia = GrantedVia.MINI_APP
) -> GrantTelegramWriteAccessCommand:
    return GrantTelegramWriteAccessCommand(user_id=user_id, via=via)


async def test_write_access_opens_telegram_channel(notifications: Notifications) -> None:
    user_id, chat_id = await notifications.user_with_chat()

    channel = await notifications.grant(granted(user_id))

    assert channel.writable
    assert (channel.granted_via, channel.granted_at) == (
        GrantedVia.MINI_APP,
        notifications.clock.now(),
    )
    assert await notifications.channels(user_id) == [
        {
            "kind": "telegram",
            "address": str(chat_id),
            "granted_via": "mini_app",
            "granted_at": notifications.clock.now(),
            "disabled_at": None,
        }
    ]


async def test_repeated_permission_changes_nothing(notifications: Notifications) -> None:
    user_id, _ = await notifications.user_with_chat()
    first = await notifications.grant(granted(user_id, GrantedVia.BOT_START))
    notifications.clock.advance(timedelta(hours=1))

    again = await notifications.grant(granted(user_id, GrantedVia.MINI_APP))

    assert again == first
    [row] = await notifications.channels(user_id)
    assert (row["granted_via"], row["granted_at"]) == ("bot_start", first.granted_at)


async def test_permission_enables_blocked_channel_again(notifications: Notifications) -> None:
    user_id, _ = await notifications.user_with_chat()
    await notifications.grant(granted(user_id, GrantedVia.BOT_START))
    await notifications.session.execute(
        # время — по часам теста, а не now() базы: часы теста стоят на 5 октября 2026, 09:00 UTC, и
        # с реальным now() позже них «выключено» оказывалось позже «включено» — тест падал по часам
        text("UPDATE notifications.channels SET disabled_at = :at WHERE user_id = :user_id"),
        {"user_id": user_id, "at": notifications.clock.now()},
    )
    await notifications.session.commit()
    notifications.clock.advance(timedelta(days=1))

    channel = await notifications.grant(granted(user_id))

    assert channel.writable
    assert (channel.granted_via, channel.granted_at) == (
        GrantedVia.MINI_APP,
        notifications.clock.now(),
    )
    assert len(await notifications.channels(user_id)) == 1


async def test_write_access_is_announced_only_when_it_becomes_possible(
    notifications: Notifications,
) -> None:
    """Метрика «Opt-in уведомлений» (1.7): событие — переход в «можно писать», а не каждый
    /start и не каждый повтор requestWriteAccess."""
    user_id, _ = await notifications.user_with_chat()
    await notifications.grant(granted(user_id, GrantedVia.MINI_APP))
    await notifications.grant(granted(user_id, GrantedVia.BOT_START))  # повтор: уже можно
    await notifications.session.execute(
        # время — по часам теста, а не now() базы: часы теста стоят на 5 октября 2026, 09:00 UTC, и
        # с реальным now() позже них «выключено» оказывалось позже «включено» — тест падал по часам
        text("UPDATE notifications.channels SET disabled_at = :at WHERE user_id = :user_id"),
        {"user_id": user_id, "at": notifications.clock.now()},
    )
    await notifications.session.commit()
    notifications.clock.advance(timedelta(minutes=1))
    await notifications.grant(granted(user_id, GrantedVia.BOT_START))  # включился снова

    announced = await notifications.announced(user_id)
    assert [event["via"] for event in announced] == ["mini_app", "bot_start"]


async def test_chat_follows_its_new_account(notifications: Notifications) -> None:
    """Тот же Telegram у другого аккаунта (пересоздан после удаления): адрес один."""
    old_user, chat_id = await notifications.user_with_chat()
    await notifications.grant(granted(old_user))
    new_user, _ = await notifications.user_with_chat()
    notifications.identity.chats[new_user] = chat_id

    await notifications.grant(granted(new_user))

    assert await notifications.channels(old_user) == []
    [row] = await notifications.channels(new_user)
    assert row["address"] == str(chat_id)


async def test_user_without_telegram_has_no_channel(notifications: Notifications) -> None:
    with pytest.raises(TelegramNotLinkedError):
        await notifications.grant(granted(UserId(new_id())))


# --- подписчик BotStarted -----------------------------------------------------------------


def test_notifications_subscribes_to_bot_started() -> None:
    event = BotStarted(user_id=UserId(new_id()), occurred_at=NOW)
    assert GRANT_WRITE_ACCESS in TASKS.event_registry().subscribers(event)


async def test_bot_start_opens_channel_idempotently(notifications: Notifications) -> None:
    user_id, chat_id = await notifications.user_with_chat()
    payload = {"user_id": str(user_id), "occurred_at": NOW.isoformat()}
    event = TypeAdapter(BotStarted).validate_python(payload | {"event_id": str(new_id())})

    await grant_write_access(event, notifications.grant)
    await grant_write_access(event, notifications.grant)

    [row] = await notifications.channels(user_id)
    assert (row["address"], row["granted_via"], row["disabled_at"]) == (
        str(chat_id),
        "bot_start",
        None,
    )
