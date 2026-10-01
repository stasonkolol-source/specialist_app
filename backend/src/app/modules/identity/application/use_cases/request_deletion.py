"""Запрос на удаление аккаунта (S45, POST /me/deletion): grace-период 7 дней, исполнит задача
`identity.process_deletions`. Повтор отдаёт тот же запрос — срок не сдвигается.

До исполнения аккаунт работает как обычно: передумавший отменяет запрос (DELETE /me/deletion).
Санкции запросу не мешают: удалить свои данные можно и под ограничением.
"""

from dataclasses import dataclass

from app.modules.identity.application.ports import DeletionRepository, UserRepository
from app.modules.identity.domain.deletion import DeletionRequest, DeletionSource
from app.platform.db.port import UnitOfWork
from app.platform.db.retry import retry_on_conflict
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestDeletionCommand:
    actor_id: UserId
    source: DeletionSource


class RequestDeletion:
    def __init__(
        self, uow: UnitOfWork, users: UserRepository, deletions: DeletionRepository, clock: Clock
    ) -> None:
        self._uow, self._users, self._deletions, self._clock = uow, users, deletions, clock

    async def __call__(self, cmd: RequestDeletionCommand) -> DeletionRequest:
        now = self._clock.now()

        async def attempt() -> DeletionRequest:
            async with self._uow:
                user = await self._users.get_for_update(cmd.actor_id)
                user.ensure_active()
                pending = await self._deletions.active_for_update(cmd.actor_id)
                if pending is not None:
                    return pending
                request = DeletionRequest.request(cmd.actor_id, source=cmd.source, now=now)
                await self._deletions.add(request)
                return request

        return await retry_on_conflict(attempt)
