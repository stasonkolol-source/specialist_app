"""Ответы Bot API при отправке (DEVELOPMENT_PLAN 2.3b, ARCHITECTURE §12.4).

«Готово, когда»: 403 выключает канал; 429 ставит паузу. Ещё: 400 — без повтора, сбой сети —
повтор до предела попыток, срочное уходит из очереди раньше.
"""

from datetime import timedelta
from uuid import UUID

import pytest

from app.modules.notifications.application.use_cases.block_telegram_channel import (
    BlockTelegramChannelCommand,
)
from app.modules.notifications.application.use_cases.expire_stale_deliveries import (
    ExpireStaleDeliveriesCommand,
)
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccessCommand,
)
from app.modules.notifications.application.use_cases.notify import NotifyCommand
from app.modules.notifications.application.use_cases.send_delivery import (
    MAX_ATTEMPTS,
    SendDeliveryCommand,
)
from app.modules.notifications.domain.catalog import NotificationType
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.domain.notification import DeliveryId, DeliveryStatus
from app.modules.notifications.tests.integration.conftest import Notifications
from app.platform.kernel.errors import ExternalServiceError, RateLimitedError
from app.platform.kernel.ids import UserId
from app.platform.telegram.port import TelegramBlockedError, TelegramRejectedError

pytestmark = pytest.mark.integration


def restricted(user_id: UserId, key: str = "r1") -> NotifyCommand:
    return NotifyCommand(
        user_id=user_id,
        type=NotificationType.ACCOUNT_RESTRICTED,
        dedupe_key=f"account.restricted:{key}",
        params={"kind": "posting_blocked"},
        link="l_terms",
    )


async def queued_delivery(
    notifications: Notifications, user_id: UserId, key: str = "r1"
) -> DeliveryId:
    await notifications.notify(restricted(user_id, key))
    tasks = await notifications.sends()
    return DeliveryId(UUID(str(tasks[-1].payload["delivery_id"])))


async def test_sender_403_turns_the_channel_off(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()
    delivery_id = await queued_delivery(notifications, user_id)
    notifications.sender.error = TelegramBlockedError()
    notifications.clock.advance(timedelta(minutes=5))  # остановил бота после /start

    status = await notifications.send(SendDeliveryCommand(delivery_id=delivery_id))

    assert status is DeliveryStatus.FAILED
    [delivery] = await notifications.deliveries(user_id)
    assert (delivery["status"], delivery["attempts"]) == ("failed", 1)
    [channel] = await notifications.channels(user_id)
    assert channel["disabled_at"] == notifications.clock.now()
    # дальше бот ему не пишет: уведомление остаётся только в центре
    await notifications.notify(restricted(user_id, "r2"))
    assert len(await notifications.deliveries(user_id)) == 1


async def test_sender_429_pauses_without_spending_an_attempt(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()
    delivery_id = await queued_delivery(notifications, user_id)
    await notifications.take_sends()
    notifications.sender.error = RateLimitedError(retry_after=17)

    assert await notifications.send(SendDeliveryCommand(delivery_id=delivery_id)) is None

    later = notifications.clock.now() + timedelta(seconds=17)
    [delivery] = await notifications.deliveries(user_id)
    assert (delivery["status"], delivery["not_before"], delivery["attempts"]) == (
        "queued",
        later,
        0,
    )
    [task] = await notifications.sends()
    assert task.scheduled_at == later
    notifications.sender.error = None
    notifications.clock.set(later)
    assert await notifications.send(SendDeliveryCommand(delivery_id=delivery_id)) == "sent"


async def test_sender_400_fails_without_retry(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()
    delivery_id = await queued_delivery(notifications, user_id)
    notifications.sender.error = TelegramRejectedError("Bad Request: can't parse entities")

    status = await notifications.send(SendDeliveryCommand(delivery_id=delivery_id))

    assert status is DeliveryStatus.FAILED
    [delivery] = await notifications.deliveries(user_id)
    assert delivery["status"] == "failed"
    [channel] = await notifications.channels(user_id)
    assert channel["disabled_at"] is None  # канал цел: виновато сообщение


async def test_sender_outage_is_retried_then_given_up(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()
    delivery_id = await queued_delivery(notifications, user_id)
    notifications.sender.failing = True

    for _ in range(MAX_ATTEMPTS - 1):
        with pytest.raises(ExternalServiceError):  # повтор задачи
            await notifications.send(SendDeliveryCommand(delivery_id=delivery_id))
    status = await notifications.send(SendDeliveryCommand(delivery_id=delivery_id))

    assert status is DeliveryStatus.FAILED
    [delivery] = await notifications.deliveries(user_id)
    assert (delivery["status"], delivery["attempts"]) == ("failed", MAX_ATTEMPTS)


async def test_sender_queue_takes_urgent_types_first(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()

    await notifications.notify(restricted(user_id))  # P0
    await notifications.notify(
        NotifyCommand(
            user_id=user_id, type=NotificationType.JOB_EXPIRING, dedupe_key="job.expiring:1"
        )
    )  # P3

    assert [t.priority for t in await notifications.sends()] == [3, 0]


async def test_late_start_does_not_undo_a_later_stop(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()
    now = notifications.clock.now()
    start, stop = now + timedelta(seconds=10), now + timedelta(seconds=20)

    await notifications.block(BlockTelegramChannelCommand(user_id=user_id, at=stop))
    # задача BotStarted, нажатого раньше остановки, отработала позже неё
    await notifications.grant(
        GrantTelegramWriteAccessCommand(user_id=user_id, via=GrantedVia.BOT_START, at=start)
    )

    [channel] = await notifications.channels(user_id)
    assert channel["disabled_at"] == stop
    assert len(await notifications.announced(user_id)) == 1  # только первый /start


async def test_start_after_a_stop_turns_the_channel_back_on(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()
    now = notifications.clock.now()

    await notifications.block(
        BlockTelegramChannelCommand(user_id=user_id, at=now + timedelta(seconds=20))
    )
    await notifications.grant(
        GrantTelegramWriteAccessCommand(
            user_id=user_id, via=GrantedVia.BOT_START, at=now + timedelta(seconds=30)
        )
    )

    [channel] = await notifications.channels(user_id)
    assert channel["disabled_at"] is None


async def test_stale_queued_deliveries_are_given_up(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()
    await notifications.notify(restricted(user_id, "old"))
    notifications.clock.advance(timedelta(days=1, hours=1))  # задачу отправки потеряли
    await notifications.notify(restricted(user_id, "fresh"))

    assert await notifications.expire(ExpireStaleDeliveriesCommand()) == 1

    statuses = [d["status"] for d in await notifications.deliveries(user_id)]
    assert statuses == ["failed", "queued"]
