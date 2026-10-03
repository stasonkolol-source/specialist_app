"""Правило хранения переписки (periodic `messaging.purge_messages`; DEVELOPMENT_PLAN 6.3a,
ARCHITECTURE §7.10): текст сообщений старше 12 месяцев стирается порциями."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from app.modules.messaging.application.ports import MessageStore
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

RETENTION: Final = timedelta(days=365)
BATCH: Final = 1000


@dataclass(frozen=True, slots=True, kw_only=True)
class PurgeMessagesCommand:
    limit: int = BATCH


class PurgeMessages:
    def __init__(self, uow: UnitOfWork, messages: MessageStore, clock: Clock) -> None:
        self._uow, self._messages, self._clock = uow, messages, clock

    async def __call__(self, cmd: PurgeMessagesCommand) -> int:
        now = self._clock.now()
        async with self._uow:
            return await self._messages.purge(now - RETENTION, now=now, limit=cmd.limit)
