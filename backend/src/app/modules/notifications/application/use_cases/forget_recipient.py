"""Удалённый аккаунт (подписчик UserDeleted; ARCHITECTURE §7.10): лента уведомлений, доставки,
каналы, предпочтения и настройки получателя удалены. Повтор задачи ничего не меняет."""

from dataclasses import dataclass

from app.modules.notifications.application.ports import RecipientData
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetRecipientCommand:
    user_id: UserId


class ForgetRecipient:
    def __init__(self, uow: UnitOfWork, data: RecipientData) -> None:
        self._uow, self._data = uow, data

    async def __call__(self, cmd: ForgetRecipientCommand) -> None:
        async with self._uow:
            await self._data.forget(cmd.user_id)
