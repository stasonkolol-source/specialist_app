"""Удалить свой файл (DELETE /media/{id}): мягкое удаление, повтор — без изменений.

Объект из incoming удаляется после commit и без гарантии: не вышло — его уберёт lifecycle
бакета через 2 дня. Недогруженная multipart-загрузка отменяется. Варианты в media и
отвязка от профиля или заявки — шаги 2.2, 2.8a и 5.1.
"""

from dataclasses import dataclass

import structlog

from app.modules.media.application.ports import MediaRepository
from app.modules.media.domain.asset import MediaStatus
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import ExternalServiceError
from app.platform.kernel.ids import MediaId, UserId
from app.platform.storage.port import Bucket, StoragePort, StorageRejectedError

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class DeleteMediaCommand:
    owner_id: UserId
    media_id: MediaId


class DeleteMedia:
    def __init__(
        self, uow: UnitOfWork, assets: MediaRepository, storage: StoragePort, clock: Clock
    ) -> None:
        self._uow, self._assets, self._storage, self._clock = uow, assets, storage, clock

    async def __call__(self, cmd: DeleteMediaCommand) -> None:
        async with self._uow:
            asset = await self._assets.get_for_update(cmd.owner_id, cmd.media_id)
            pending = asset.status is MediaStatus.PENDING_UPLOAD
            deleted = asset.delete(now=self._clock.now())
            await self._assets.save(asset)
        if not deleted:
            return
        bucket = Bucket(asset.bucket)
        try:
            if pending and asset.upload_id is not None:
                await self._storage.abort_multipart(
                    bucket, asset.object_key, upload_id=asset.upload_id
                )
            await self._storage.delete(bucket, asset.object_key)
        except (StorageRejectedError, ExternalServiceError) as exc:
            log.warning("media_object_not_deleted", media_id=str(asset.id), error=str(exc))
