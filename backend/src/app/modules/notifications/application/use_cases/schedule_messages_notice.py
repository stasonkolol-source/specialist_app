"""Поставить уведомление о сообщениях (`message.received`, ARCHITECTURE §11.3; DEVELOPMENT_PLAN
6.3b): дебаунс окном. Первое сообщение диалога получателю ставит задачу на конец окна; пока она
ждёт, следующие ничего не ставят — замок очереди по диалогу и получателю. Пять сообщений за
минуту — одно уведомление «Новых сообщений: 5».
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.notifications.application.ports import (
    MESSAGES_DEBOUNCE,
    NOTIFY_MESSAGES,
    MessagesWindow,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId
from app.platform.queue.port import JobQueue


@dataclass(frozen=True, slots=True, kw_only=True)
class ScheduleMessagesNoticeCommand:
    conversation_id: UUID
    recipient_id: UserId
    at: datetime
    """Когда пришло сообщение: окно закрывается через MESSAGES_DEBOUNCE после первого."""


class ScheduleMessagesNotice:
    def __init__(self, uow: UnitOfWork, queue: JobQueue) -> None:
        self._uow, self._queue = uow, queue

    async def __call__(self, cmd: ScheduleMessagesNoticeCommand) -> None:
        async with self._uow:
            await self._queue.enqueue(
                NOTIFY_MESSAGES,
                MessagesWindow(
                    conversation_id=cmd.conversation_id,
                    recipient_id=cmd.recipient_id,
                    since=cmd.at,
                ),
                dedup_key=f"{cmd.conversation_id}:{cmd.recipient_id}",
                not_before=cmd.at + MESSAGES_DEBOUNCE,
            )
