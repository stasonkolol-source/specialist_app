"""Разблокировать (DELETE /me/blocks/{user_id}; S44, меню S08 и S30; DEVELOPMENT_PLAN 4.7):
снимается только своя блокировка — чужая (меня заблокировали) остаётся. Блокировки не было —
тоже 204."""

from dataclasses import dataclass

from app.modules.identity.application.ports import Blocks
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class UnblockUserCommand:
    actor_id: UserId
    user_id: UserId


class UnblockUser:
    def __init__(self, uow: UnitOfWork, blocks: Blocks) -> None:
        self._uow, self._blocks = uow, blocks

    async def __call__(self, cmd: UnblockUserCommand) -> None:
        async with self._uow:
            await self._blocks.remove(cmd.actor_id, cmd.user_id)
