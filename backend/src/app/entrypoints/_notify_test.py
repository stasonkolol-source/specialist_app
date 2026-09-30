"""`cli notify-test`: тестовое уведомление через весь конвейер (DEVELOPMENT_PLAN 2.3b).

Notify создаёт уведомление `system.test` и доставку в бот, а отправляет её воркер — тем же
путём, что и любое уведомление: очередь `notifications`, лимитер, Bot API. Команда ждёт
итога доставки и печатает его; не дождалась — скорее всего, воркер не запущен. Сама
команда не отправляет: иначе она соревновалась бы с воркером за ту же доставку.
"""

import asyncio
from dataclasses import dataclass

from dishka import AsyncContainer

WAIT_SECONDS = 30.0
POLL_SECONDS = 0.5


@dataclass(frozen=True, slots=True)
class NotifyTestOutcome:
    sent: bool
    message: str


async def run_notify_test(
    container: AsyncContainer, user_ref: str, *, wait: float = WAIT_SECONDS
) -> NotifyTestOutcome:
    """Тестовое уведомление пользователю (Telegram id или внутренний id) и его итог."""
    from app.modules.identity.api import IdentityApi
    from app.modules.notifications.application.ports import NotificationQuery
    from app.modules.notifications.application.use_cases.notify import Notify, NotifyCommand
    from app.modules.notifications.domain.catalog import NotificationType
    from app.modules.notifications.domain.notification import DeliveryStatus
    from app.platform.kernel.ids import UserId, new_id, parse_id

    async with container() as request:
        identity = await request.get(IdentityApi)
        user_id: UserId | None = None
        if user_ref.isdigit():
            telegram_user = await identity.by_telegram(int(user_ref))
            user_id = telegram_user.id if telegram_user else None
        else:
            try:
                summary = await identity.get_user(UserId(parse_id(user_ref)))
            except ValueError:
                summary = None
            user_id = summary.id if summary and not summary.is_deleted else None
        if user_id is None:
            return NotifyTestOutcome(sent=False, message=f"notify-test: no such user {user_ref}")
        notify = await request.get(Notify)
        notification_id = await notify(
            NotifyCommand(
                user_id=user_id,
                type=NotificationType.SYSTEM_TEST,
                dedupe_key=f"system.test:{new_id()}",
                link="h",
                urgent=True,
            )
        )
        query = await request.get(NotificationQuery)
        deliveries = await query.deliveries_of(notification_id) if notification_id else []
    if not deliveries:
        return NotifyTestOutcome(
            sent=False,
            message=f"user {user_id}: the bot may not write to them — ask them to press /start",
        )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    while True:
        async with container() as request:
            target = await (await request.get(NotificationQuery)).delivery(deliveries[0])
        if target is not None and target.status is not DeliveryStatus.QUEUED:
            return NotifyTestOutcome(
                sent=target.status is DeliveryStatus.SENT,
                message=f"user {user_id}: {target.status}",
            )
        if loop.time() >= deadline:
            return NotifyTestOutcome(
                sent=False,
                message=f"user {user_id}: still queued after {wait:.0f}s — is the worker running?",
            )
        await asyncio.sleep(POLL_SECONDS)
