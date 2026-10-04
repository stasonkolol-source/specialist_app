"""Хэши удалённых аккаунтов старше 12 месяцев (правило `identity.deleted_identity_hashes`
ночной `platform.retention_sweep`; ARCHITECTURE §7.10, 2.12b).

Хэш нужен антифроду: повторная регистрация того же Telegram — сигнал риска. Через 12 месяцев
после удаления он удаляется, и та же регистрация сигнала не даёт. Транзакция — на страницу.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.modules.identity.application.ports import DeletedIdentities
from app.platform.db.port import UnitOfWork

BATCH: Final = 1000


@dataclass(frozen=True, slots=True, kw_only=True)
class PurgeIdentityHashesCommand:
    now: datetime
    limit: int = BATCH


class PurgeIdentityHashes:
    def __init__(self, uow: UnitOfWork, hashes: DeletedIdentities) -> None:
        self._uow, self._hashes = uow, hashes

    async def __call__(self, cmd: PurgeIdentityHashesCommand) -> int:
        purged = 0
        while True:
            async with self._uow:
                page = await self._hashes.purge(cmd.now, limit=cmd.limit)
            purged += page
            if page < cmd.limit:
                return purged
