"""Недогруженные файлы (periodic `media.cleanup_orphans`, DEVELOPMENT_PLAN 2.1).

`pending_upload` старше суток — `failed` (abandoned): клиент начал загрузку и не закончил.
Запись остаётся для истории, объект и незавершённый multipart убирает задача
`media.delete_object` после commit (ADR-0020 §3, ARCHITECTURE §10.5).
"""

from dataclasses import dataclass
from datetime import timedelta

from app.modules.media.application.ports import DELETE_OBJECT, MediaRepository
from app.modules.media.application.uploads import delete_payload
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.queue.port import JobQueue

ORPHAN_AFTER = timedelta(hours=24)
BATCH = 500


@dataclass(frozen=True, slots=True, kw_only=True)
class CleanupOrphansCommand:
    older_than: timedelta = ORPHAN_AFTER
    limit: int = BATCH


class CleanupOrphans:
    def __init__(
        self, uow: UnitOfWork, assets: MediaRepository, queue: JobQueue, clock: Clock
    ) -> None:
        self._uow, self._assets, self._queue, self._clock = uow, assets, queue, clock

    async def __call__(self, cmd: CleanupOrphansCommand) -> int:
        """Число помеченных `failed`."""
        async with self._uow:
            orphans = await self._assets.pending_before(
                self._clock.now() - cmd.older_than, limit=cmd.limit
            )
            for asset in orphans:
                asset.abandon()
                await self._assets.save(asset)
                await self._queue.enqueue(
                    DELETE_OBJECT, delete_payload(asset), dedup_key=str(asset.id)
                )
        return len(orphans)
