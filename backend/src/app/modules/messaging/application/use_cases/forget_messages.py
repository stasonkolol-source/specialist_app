"""Аккаунт удалён (подписчик UserDeleted; DEVELOPMENT_PLAN 6.3a, ARCHITECTURE §7.10): текст его
сообщений стирается; вторая сторона видит «сообщение удалено»."""

from dataclasses import dataclass

from app.modules.messaging.application.ports import MessageStore
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetMessagesCommand:
    user_id: UserId


class ForgetMessages:
    def __init__(self, uow: UnitOfWork, messages: MessageStore, clock: Clock) -> None:
        self._uow, self._messages, self._clock = uow, messages, clock

    async def __call__(self, cmd: ForgetMessagesCommand) -> int:
        async with self._uow:
            return await self._messages.forget(cmd.user_id, now=self._clock.now())
