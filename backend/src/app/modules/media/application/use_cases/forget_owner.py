"""Файлы удалённого аккаунта (подписчик UserDeleted; ARCHITECTURE §7.10): каждый неудалённый
файл владельца — на удаление задачей `media.discard_media`, как DELETE /media/{id} от
владельца: варианты снимаются с публикации сразу, объекты стирает `media.purge_deleted`
через 30 дней. Файл под legal hold (доказательство открытого кейса) purge откладывает.
"""

from dataclasses import dataclass

from app.modules.media.application.dto import DiscardMediaPayload
from app.modules.media.application.ports import DISCARD_MEDIA, MediaQuery
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId
from app.platform.queue.port import JobQueue


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetOwnerCommand:
    owner_id: UserId


class ForgetOwner:
    def __init__(self, uow: UnitOfWork, query: MediaQuery, queue: JobQueue) -> None:
        self._uow, self._query, self._queue = uow, query, queue

    async def __call__(self, cmd: ForgetOwnerCommand) -> int:
        """Сколько файлов поставлено на удаление."""
        media_ids = await self._query.owned_ids(cmd.owner_id)
        async with self._uow:
            for media_id in media_ids:
                await self._queue.enqueue(
                    DISCARD_MEDIA,
                    DiscardMediaPayload(user_id=cmd.owner_id, media_id=media_id),
                    dedup_key=str(media_id),
                )
        return len(media_ids)
