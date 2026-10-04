"""Фото без итога проверки (periodic `moderation.recheck_images`, DEVELOPMENT_PLAN 6.7).

`moderation.check_image` ставится один раз по MediaReady: упала после всех повторов (сбой БД,
хранилища) или не прочитала вариант — фото навсегда осталось бы `pending`, а работа портфолио с
ним — «На проверке». Раз в 10 минут фото, обработанные больше RECHECK_AFTER назад и всё ещё без
итога, идут на проверку снова (и фото, загруженные до модерации фото); ждущие дольше
GIVE_UP_AFTER, которые проверить так и не вышло, — модератору (P2, как Unavailable).
Пачкой не больше CHUNK; в журнале — только число.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

import structlog

from app.modules.media.api import MediaApi
from app.modules.moderation.application.dto import RecheckImagePayload
from app.modules.moderation.application.ports import RECHECK_IMAGE
from app.modules.moderation.application.use_cases.check_image import IMAGE_PURPOSES
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.queue.port import JobQueue

log = structlog.get_logger(__name__)

RECHECK_AFTER: Final = timedelta(minutes=15)
"""Свежее фото проверяет задача по MediaReady: очередь могла не дойти до него за минуты."""
GIVE_UP_AFTER: Final = timedelta(hours=1)
"""Ждёт итога дольше — перепроверка, которая снова не смогла проверить (вариант не читается,
хранилище недоступно), отдаёт фото человеку: дальше ждать бессмысленно."""
CHUNK: Final = 50


@dataclass(frozen=True, slots=True, kw_only=True)
class RecheckImagesCommand:
    limit: int = CHUNK


class RecheckImages:
    def __init__(self, uow: UnitOfWork, media: MediaApi, queue: JobQueue, clock: Clock) -> None:
        self._uow, self._media, self._queue, self._clock = uow, media, queue, clock

    async def __call__(self, cmd: RecheckImagesCommand) -> int:
        now = self._clock.now()
        images = await self._media.unchecked_images(
            processed_before=now - RECHECK_AFTER, purposes=IMAGE_PURPOSES, limit=cmd.limit
        )
        if not images:
            return 0
        async with self._uow:
            for image in images:
                await self._queue.enqueue(
                    RECHECK_IMAGE,
                    RecheckImagePayload(
                        media_id=image.media_id,
                        owner_id=image.owner_id,
                        purpose=image.purpose,
                        give_up=image.processed_at < now - GIVE_UP_AFTER,
                    ),
                    dedup_key=str(image.media_id),
                )
        log.info("moderation_images_rechecked", count=len(images))
        return len(images)
