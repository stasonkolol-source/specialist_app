"""Удалить свой файл (DELETE /media/{id}): мягкое удаление, повтор — без изменений.

Загруженный файл сразу снимается с показа, а объекты хранятся ещё 30 дней: их удаляет
`media.purge_deleted` (шаг 2.2, ARCHITECTURE §10.5). Недогруженный файл хранить незачем:
его объект и multipart убирает задача `media.delete_object` после commit (ADR-0020 §3).
Отвязка от профиля или заявки — шаги 2.8a и 5.1.
"""

from dataclasses import dataclass

from app.modules.media.application.ports import DELETE_OBJECT, MediaRepository
from app.modules.media.application.uploads import delete_payload
from app.modules.media.domain.asset import MediaStatus
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import MediaId, UserId
from app.platform.queue.port import JobQueue


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
            unfinished = asset.status is MediaStatus.PENDING_UPLOAD
            if not asset.delete(now=self._clock.now()):
                return
            await self._assets.save(asset)
            if unfinished:
                await self._queue.enqueue(
                    DELETE_OBJECT, delete_payload(asset), dedup_key=str(asset.id)
                )
