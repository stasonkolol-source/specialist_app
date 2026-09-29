"""Задачи media (ARCHITECTURE §10, §12.3).

- `media.process` — подписчик MediaUploaded в очереди `media` (worker-media). Обработка
  (magic bytes, EXIF, варианты, pHash, модерация) — шаг 2.2; до него файл остаётся
  `uploaded`, а задача только отмечает, что файл дошёл.
- `media.delete_object` — убрать из хранилища недогруженный или не тот файл; сбой
  хранилища (5xx) — повтор по стратегии очереди.
- `media.cleanup_orphans` — раз в час: недогруженные за сутки загрузки → `failed`.
"""

from contextlib import suppress

import structlog
from dishka import FromDishka

from app.modules.media.application.dto import DeleteObjectPayload
from app.modules.media.application.ports import DELETE_OBJECT, PROCESS_MEDIA
from app.modules.media.application.use_cases.cleanup_orphans import (
    CleanupOrphans,
    CleanupOrphansCommand,
)
from app.platform.contracts.events.media import MediaUploaded
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber, task
from app.platform.storage.port import Bucket, StoragePort, StorageRejectedError

log = structlog.get_logger(__name__)


@subscriber(MediaUploaded, PROCESS_MEDIA)
async def process(event: MediaUploaded) -> None:
    log.info("media_uploaded", media_id=str(event.media_id), kind=event.kind)


@task(DELETE_OBJECT)
async def delete_object(payload: DeleteObjectPayload, storage: FromDishka[StoragePort]) -> None:
    bucket = Bucket(payload.bucket)
    if payload.upload_id is not None:
        # multipart уже собран или отменён — хранилище откажет (4xx): остаётся удалить объект
        with suppress(StorageRejectedError):
            await storage.abort_multipart(bucket, payload.object_key, upload_id=payload.upload_id)
    await storage.delete(bucket, payload.object_key)
    log.info("media_object_deleted", media_id=str(payload.media_id))


@periodic("media.cleanup_orphans", cron="41 * * * *")
async def cleanup_orphans(run: PeriodicRun) -> None:
    async with run.container() as request:
        cleanup = await request.get(CleanupOrphans)
        abandoned = await cleanup(CleanupOrphansCommand())
    if abandoned:
        log.info("media_orphans_abandoned", count=abandoned)
