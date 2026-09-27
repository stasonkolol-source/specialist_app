"""Задачи notifications (ADR-0020 §3): подписки на события других модулей.

`/start` в боте обрабатывает identity (он регистрирует пользователя), а канал доставки —
данные notifications. identity ниже по DAG (ARCHITECTURE §5.4) и фасад notifications не
вызывает: он публикует `BotStarted`, а канал открывает этот подписчик после commit.
"""

from dishka import FromDishka

from app.modules.notifications.application.ports import GRANT_WRITE_ACCESS
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
    GrantTelegramWriteAccessCommand,
)
from app.modules.notifications.domain.channel import GrantedVia
from app.platform.contracts.events.identity import BotStarted
from app.platform.queue.tasks import subscriber


@subscriber(BotStarted, GRANT_WRITE_ACCESS)
async def grant_write_access(
    event: BotStarted, grant: FromDishka[GrantTelegramWriteAccess]
) -> None:
    """Канал telegram доступен после /start; повтор задачи ничего не меняет."""
    await grant(GrantTelegramWriteAccessCommand(user_id=event.user_id, via=GrantedVia.BOT_START))
