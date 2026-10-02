"""Отмена запроса на удаление (S45, DELETE /me/deletion): пока он не исполнен. Запроса нет —
ничего: отмена идемпотентна."""

from dataclasses import dataclass

from app.modules.identity.application.ports import DeletionRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelDeletionCommand:
    actor_id: UserId


class CancelDeletion:
    def __init__(self, uow: UnitOfWork, deletions: DeletionRepository, clock: Clock) -> None:
        self._uow, self._deletions, self._clock = uow, deletions, clock

    async def __call__(self, cmd: CancelDeletionCommand) -> bool:
        """Был ли ждущий запрос."""
        async with self._uow:
            request = await self._deletions.active_for_update(cmd.actor_id)
            if request is None:
                return False
            request.cancel(now=self._clock.now())
            await self._deletions.save(request)
        return True
