"""Задачи messaging (ADR-0020 §3).

- `messaging.forget_messages` — UserDeleted: текст сообщений удалённого аккаунта стирается
  (§7.10, 6.3a).
- `messaging.purge_messages` — раз в сутки: правило хранения — текст сообщений старше 12 месяцев
  стирается порциями.
"""

from dishka import FromDishka

from app.modules.messaging.application.ports import FORGET_MESSAGES
from app.modules.messaging.application.use_cases.forget_messages import (
    ForgetMessages,
    ForgetMessagesCommand,
)
from app.modules.messaging.application.use_cases.purge_messages import (
    PurgeMessages,
    PurgeMessagesCommand,
)
from app.platform.contracts.events.identity import UserDeleted
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber


@subscriber(UserDeleted, FORGET_MESSAGES)
async def forget_messages(event: UserDeleted, forget: FromDishka[ForgetMessages]) -> None:
    await forget(ForgetMessagesCommand(user_id=event.user_id))


@periodic("messaging.purge_messages", cron="47 3 * * *")
async def purge_messages(run: PeriodicRun) -> None:
    async with run.container() as request:
        await (await request.get(PurgeMessages))(PurgeMessagesCommand())
