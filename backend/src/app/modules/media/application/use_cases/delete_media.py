"""Удалить свой файл (DELETE /media/{id}): мягкое удаление, повтор — без изменений.

Файл сразу снят с показа: API его больше не отдаёт, а публичные варианты задача
`media.hide_variants` переносит в приватный бакет — по старой ссылке их уже не открыть.
Объекты хранятся ещё 30 дней и удаляются `media.purge_deleted` (ARCHITECTURE §10.5).
Недогруженный файл хранить незачем: его объект и multipart сразу убирает
`media.delete_objects`. Внешняя запись — задачами после commit (ADR-0020 §3). Кэш CDN
по URL сбрасывается вместе с CDN (прод-контур). Отвязка от профиля или заявки — 2.8a, 5.1.
"""

from dataclasses import dataclass

from app.modules.media.application.dto import HideVariantsPayload
from app.modules.media.application.ports import DELETE_OBJECTS, HIDE_VARIANTS, MediaRepository
from app.modules.media.application.uploads import delete_original
from app.modules.media.domain.asset import MEDIA_BUCKET, MediaStatus, variant_bucket
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import MediaId, UserId
from app.platform.queue.port import JobQueue

HAS_VARIANTS = frozenset({MediaStatus.READY, MediaStatus.PROCESSING})
"""Варианты уже есть или вот-вот появятся (обработка идёт): их прячет media.hide_variants."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DeleteMediaCommand:
    owner_id: UserId
    media_id: MediaId


class DeleteMedia:
    def __init__(
        self, uow: UnitOfWork, assets: MediaRepository, queue: JobQueue, clock: Clock
    ) -> None:
        self._uow, self._assets, self._queue, self._clock = uow, assets, queue, clock

    async def __call__(self, cmd: DeleteMediaCommand) -> None:
        async with self._uow:
            asset = await self._assets.get_for_update(cmd.owner_id, cmd.media_id)
            before = asset.status
            if not asset.delete(now=self._clock.now()):
                return
            await self._assets.save(asset)
            if before is MediaStatus.PENDING_UPLOAD:
                await self._queue.enqueue(
                    DELETE_OBJECTS, delete_original(asset), dedup_key=f"original:{asset.id}"
                )
            elif before in HAS_VARIANTS and variant_bucket(asset.purpose) == MEDIA_BUCKET:
                await self._queue.enqueue(
                    HIDE_VARIANTS,
                    HideVariantsPayload(media_id=asset.id, keys=asset.variant_keys()),
                    dedup_key=str(asset.id),
                )
