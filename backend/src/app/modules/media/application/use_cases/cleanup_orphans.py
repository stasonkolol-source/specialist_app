"""Недогруженные файлы (periodic `media.cleanup_orphans`, DEVELOPMENT_PLAN 2.1).

`pending_upload` старше суток — `failed` (abandoned): клиент начал загрузку и не закончил.
Их multipart отменяется, сами объекты incoming убирает lifecycle бакета.
"""

from dataclasses import dataclass
from datetime import timedelta

import structlog

from app.modules.media.application.ports import MediaRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import ExternalServiceError
from app.platform.storage.port import Bucket, StoragePort, StorageRejectedError

log = structlog.get_logger(__name__)

ORPHAN_AFTER = timedelta(hours=24)
BATCH = 500


@dataclass(frozen=True, slots=True, kw_only=True)
class CleanupOrphansCommand:
    older_than: timedelta = ORPHAN_AFTER
    limit: int = BATCH


class CleanupOrphans:
    def __init__(
        self, uow: UnitOfWork, assets: MediaRepository, storage: StoragePort, clock: Clock
    ) -> None:
        self._uow, self._assets, self._storage, self._clock = uow, assets, storage, clock

    async def __call__(self, cmd: CleanupOrphansCommand) -> int:
        """Число помеченных `failed`."""
        async with self._uow:
            orphans = await self._assets.pending_before(
                self._clock.now() - cmd.older_than, limit=cmd.limit
            )
            for asset in orphans:
                asset.abandon()
                await self._assets.save(asset)
        for asset in orphans:
            if asset.upload_id is None:
                continue
            try:
                await self._storage.abort_multipart(
                    Bucket(asset.bucket), asset.object_key, upload_id=asset.upload_id
                )
            except (StorageRejectedError, ExternalServiceError) as exc:
                log.warning("media_multipart_not_aborted", media_id=str(asset.id), error=str(exc))
        return len(orphans)
