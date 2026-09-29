"""Завершить загрузку (POST /media/uploads/{id}/complete, ARCHITECTURE §10.2).

Multipart собирается из частей клиента, затем HEAD сверяет размер и тип с заявленными:
совпали — `uploaded` и `MediaUploaded` (задача `media.process`) в одной транзакции; не
совпали — `failed`, а объект убирает задача. Повтор после загрузки ничего не меняет: ответ
на первый вызов мог потеряться. Сетевые вызовы — вне транзакции (ADR-0020 §3): файл читается
без блокировки, строка блокируется только для перехода статуса.

Список частей сверяется с планом до хранилища: собранный из неполного набора объект не
совпал бы по размеру, и загрузка пропала бы целиком. Недостающие части — 409 со списком.
"""

from collections import Counter
from dataclasses import dataclass

from app.modules.media.application.ports import (
    DELETE_OBJECT,
    MediaQuery,
    MediaRepository,
)
from app.modules.media.application.uploads import delete_payload, part_count
from app.modules.media.domain.asset import MediaAsset, MediaStatus
from app.modules.media.errors import (
    MediaNotFoundError,
    UploadIncompleteError,
    UploadMismatchError,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.ids import MediaId, UserId
from app.platform.queue.port import JobQueue
from app.platform.storage.port import Bucket, StoragePort, StorageRejectedError, UploadedPart


@dataclass(frozen=True, slots=True, kw_only=True)
class CompleteUploadCommand:
    owner_id: UserId
    media_id: MediaId
    parts: tuple[UploadedPart, ...] = ()
    """ETag частей multipart; у загрузки одним PUT — пусто."""


class CompleteUpload:
    def __init__(
        self,
        uow: UnitOfWork,
        assets: MediaRepository,
        query: MediaQuery,
        storage: StoragePort,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._assets, self._query = uow, assets, query
        self._storage, self._queue, self._clock = storage, queue, clock

    async def __call__(self, cmd: CompleteUploadCommand) -> MediaAsset:
        asset = await self._query.asset(cmd.owner_id, cmd.media_id)
        if asset is None:
            raise MediaNotFoundError(media_id=cmd.media_id)
        if asset.uploaded:
            return asset
        asset.ensure_pending()
        bucket = Bucket(asset.bucket)
        if asset.upload_id is not None:
            ensure_all_parts(asset, cmd.parts)
            try:
                await self._storage.complete_multipart(
                    bucket, asset.object_key, upload_id=asset.upload_id, parts=cmd.parts
                )
            except StorageRejectedError as exc:  # не те ETag: часть легла не туда
                raise UploadIncompleteError(reason=exc.code) from exc
        stored = await self._storage.head(bucket, asset.object_key)
        if stored is None:
            raise UploadIncompleteError(reason="not_found")
        async with self._uow:
            asset = await self._assets.get_for_update(cmd.owner_id, cmd.media_id)
            asset.complete(
                size_bytes=stored.size,
                mime_type=stored.content_type,
                etag=stored.etag,
                now=self._clock.now(),
            )
            await self._assets.save(asset)
            if asset.status is MediaStatus.FAILED:  # не тот файл: хранить его незачем
                await self._queue.enqueue(
                    DELETE_OBJECT, delete_payload(asset), dedup_key=str(asset.id)
                )
        if asset.status is MediaStatus.FAILED:
            raise UploadMismatchError()
        return asset


def ensure_all_parts(asset: MediaAsset, parts: tuple[UploadedPart, ...]) -> None:
    """Номера частей — ровно 1…N плана, без повторов; недостающие — 409 со списком."""
    expected = range(1, part_count(asset.size_bytes) + 1)
    numbers = Counter(part.part_number for part in parts)
    if any(n not in expected or count > 1 for n, count in numbers.items()):
        raise DomainValidationError(field="parts", parts=len(expected))
    missing = [n for n in expected if n not in numbers]
    if missing:
        raise UploadIncompleteError(reason="parts_missing", missing_parts=missing)
