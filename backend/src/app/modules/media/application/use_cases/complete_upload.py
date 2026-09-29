"""Завершить загрузку (POST /media/uploads/{id}/complete, ARCHITECTURE §10.2).

Multipart собирается из частей клиента, затем HEAD сверяет размер и тип с заявленными:
совпали — `uploaded` и `MediaUploaded` (задача `media.process`) в одной транзакции; не
совпали — `failed`. Повтор после загрузки ничего не меняет: ответ на первый вызов мог
потеряться. Сетевые вызовы — до транзакции, строка файла — под блокировкой.
"""

from dataclasses import dataclass

from app.modules.media.application.ports import MediaRepository
from app.modules.media.domain.asset import MediaAsset, MediaStatus
from app.modules.media.errors import UploadIncompleteError, UploadMismatchError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.ids import MediaId, UserId
from app.platform.storage.port import Bucket, StoragePort, StorageRejectedError, UploadedPart


@dataclass(frozen=True, slots=True, kw_only=True)
class CompleteUploadCommand:
    owner_id: UserId
    media_id: MediaId
    parts: tuple[UploadedPart, ...] = ()
    """ETag частей multipart; у загрузки одним PUT — пусто."""


class CompleteUpload:
    def __init__(
        self, uow: UnitOfWork, assets: MediaRepository, storage: StoragePort, clock: Clock
    ) -> None:
        self._uow, self._assets, self._storage, self._clock = uow, assets, storage, clock

    async def __call__(self, cmd: CompleteUploadCommand) -> MediaAsset:
        asset = await self._assets.get(cmd.owner_id, cmd.media_id)
        if asset.uploaded:
            return asset
        asset.ensure_pending()
        bucket = Bucket(asset.bucket)
        if asset.upload_id is not None:
            if not cmd.parts:
                raise DomainValidationError(field="parts")
            try:
                await self._storage.complete_multipart(
                    bucket, asset.object_key, upload_id=asset.upload_id, parts=cmd.parts
                )
            except StorageRejectedError as exc:  # не те ETag, часть не догружена
                raise UploadIncompleteError(reason=exc.code) from exc
        stored = await self._storage.head(bucket, asset.object_key)
        if stored is None:
            raise UploadIncompleteError(reason="not_found")
        async with self._uow:
            asset = await self._assets.get_for_update(cmd.owner_id, cmd.media_id)
            asset.complete(
                size_bytes=stored.size, mime_type=stored.content_type, now=self._clock.now()
            )
            await self._assets.save(asset)
        if asset.status is MediaStatus.FAILED:
            raise UploadMismatchError()
        return asset
