"""Задачи media (ARCHITECTURE §10, §12.3).

- `media.process` — подписчик MediaUploaded в очереди `media` (worker-media): фото →
  WebP-варианты без EXIF и ThumbHash, ролик → MP4 H.264 без метаданных и постер теми же
  вариантами (`ready`) или `rejected`.
- `media.delete_objects` — убрать объекты файла: недогруженную или брошенную загрузку,
  сырой оригинал после обработки, варианты при отказе и очистке; сбой хранилища — повтор.
- `media.hide_variants` — варианты удалённого файла из публичного media в private.
- `media.discard_media` — удалить файл, который модуль выше по DAG больше не показывает
  (работа портфолио, прежнее фото профиля): как DELETE /media/{id} владельца.
- `media.forget_owner` — UserDeleted: все файлы удалённого аккаунта — на удаление (§7.10).
- `media.hide_deleted` — каждые 15 минут: страховка, если скрытие не прошло.
- `media.retry_stuck` — каждые 15 минут: зависшую обработку поставить снова (фото — через
  15 минут после загрузки, ролик — через час), а зависшую дольше суток — отклонить.
- `media.purge_deleted` — раз в час: объекты файлов, удалённых больше 30 дней назад.
- `media.cleanup_orphans` — раз в час: недогруженные за сутки загрузки → `failed`.
"""

from contextlib import suppress

import structlog
from dishka import FromDishka

from app.modules.media.application.dto import (
    DeleteObjectsPayload,
    DiscardMediaPayload,
    HideVariantsPayload,
)
from app.modules.media.application.ports import (
    DELETE_OBJECTS,
    DISCARD_MEDIA,
    FORGET_OWNER,
    HIDE_VARIANTS,
    PROCESS_MEDIA,
)
from app.modules.media.application.use_cases.cleanup_orphans import (
    CleanupOrphans,
    CleanupOrphansCommand,
)
from app.modules.media.application.use_cases.delete_media import DeleteMedia, DeleteMediaCommand
from app.modules.media.application.use_cases.forget_owner import ForgetOwner, ForgetOwnerCommand
from app.modules.media.application.use_cases.hide_variants import (
    HideDeleted,
    HideDeletedCommand,
    HideVariants,
    HideVariantsCommand,
)
from app.modules.media.application.use_cases.process_media import (
    ProcessMedia,
    ProcessMediaCommand,
)
from app.modules.media.application.use_cases.purge_deleted import (
    PurgeDeleted,
    PurgeDeletedCommand,
)
from app.modules.media.application.use_cases.retry_stuck import RetryStuck, RetryStuckCommand
from app.modules.media.errors import MediaNotFoundError
from app.platform.contracts.events.identity import UserDeleted
from app.platform.contracts.events.media import MediaUploaded
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber, task
from app.platform.storage.port import Bucket, StoragePort, StorageRejectedError

log = structlog.get_logger(__name__)


@subscriber(MediaUploaded, PROCESS_MEDIA)
async def process(event: MediaUploaded, process_media: FromDishka[ProcessMedia]) -> None:
    status = await process_media(ProcessMediaCommand(media_id=event.media_id))
    log.info("media_processed", media_id=str(event.media_id), status=status)


@task(HIDE_VARIANTS)
async def hide_variants(payload: HideVariantsPayload, hide: FromDishka[HideVariants]) -> None:
    await hide(HideVariantsCommand(media_id=payload.media_id))


@subscriber(UserDeleted, FORGET_OWNER)
async def forget_owner(event: UserDeleted, forget: FromDishka[ForgetOwner]) -> None:
    await forget(ForgetOwnerCommand(owner_id=event.user_id))


@task(DISCARD_MEDIA)
async def discard_media(payload: DiscardMediaPayload, delete: FromDishka[DeleteMedia]) -> None:
    # файла уже нет (удалили раньше или повтор после сбоя) — удалять нечего
    with suppress(MediaNotFoundError):
        await delete(DeleteMediaCommand(owner_id=payload.user_id, media_id=payload.media_id))


@task(DELETE_OBJECTS)
async def delete_objects(payload: DeleteObjectsPayload, storage: FromDishka[StoragePort]) -> None:
    if payload.upload_id is not None and payload.objects:
        original = payload.objects[0]
        # multipart уже собран или отменён — хранилище откажет (4xx): остаётся удалить объект
        with suppress(StorageRejectedError):
            await storage.abort_multipart(
                Bucket(original.bucket), original.key, upload_id=payload.upload_id
            )
    for item in payload.objects:  # объекта нет — не ошибка: повтор после сбоя проходит
        await storage.delete(Bucket(item.bucket), item.key)
    log.info("media_objects_deleted", media_id=str(payload.media_id), count=len(payload.objects))


@periodic("media.hide_deleted", cron="7,22,37,52 * * * *")
async def hide_deleted(run: PeriodicRun) -> None:
    async with run.container() as request:
        hide = await request.get(HideDeleted)
        await hide(HideDeletedCommand())


@periodic("media.retry_stuck", cron="*/15 * * * *")
async def retry_stuck(run: PeriodicRun) -> None:
    async with run.container() as request:
        retry = await request.get(RetryStuck)
        await retry(RetryStuckCommand())


@periodic("media.purge_deleted", cron="37 * * * *")
async def purge_deleted(run: PeriodicRun) -> None:
    async with run.container() as request:
        purge = await request.get(PurgeDeleted)
        purged = await purge(PurgeDeletedCommand())
    if purged:
        log.info("media_deleted_purged", count=purged)


@periodic("media.cleanup_orphans", cron="41 * * * *")
async def cleanup_orphans(run: PeriodicRun) -> None:
    async with run.container() as request:
        cleanup = await request.get(CleanupOrphans)
        abandoned = await cleanup(CleanupOrphansCommand())
    if abandoned:
        log.info("media_orphans_abandoned", count=abandoned)
