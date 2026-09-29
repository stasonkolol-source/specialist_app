"""Задачи media (ARCHITECTURE §10, §12.3).

- `media.process` — подписчик MediaUploaded в очереди `media` (worker-media). Обработка
  (magic bytes, EXIF, варианты, pHash, модерация) — шаг 2.2; до него файл остаётся
  `uploaded`, а задача только отмечает, что файл дошёл.
- `media.cleanup_orphans` — раз в час: недогруженные за сутки загрузки → `failed`.
"""

import structlog

from app.modules.media.application.ports import PROCESS_MEDIA
from app.modules.media.application.use_cases.cleanup_orphans import (
    CleanupOrphans,
    CleanupOrphansCommand,
)
from app.platform.contracts.events.media import MediaUploaded
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber

log = structlog.get_logger(__name__)


@subscriber(MediaUploaded, PROCESS_MEDIA)
async def process(event: MediaUploaded) -> None:
    log.info("media_uploaded", media_id=str(event.media_id), kind=event.kind)


@periodic("media.cleanup_orphans", cron="41 * * * *")
async def cleanup_orphans(run: PeriodicRun) -> None:
    async with run.container() as request:
        cleanup = await request.get(CleanupOrphans)
        abandoned = await cleanup(CleanupOrphansCommand())
    if abandoned:
        log.info("media_orphans_abandoned", count=abandoned)
