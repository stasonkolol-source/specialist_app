"""Стереть объекты удалённых файлов (periodic `media.purge_deleted`, ARCHITECTURE §10.5).

Удалённый пользователем файл сразу снят с показа, а его объекты (оригинал и варианты — в
media или уже в private) живут ещё 30 дней: потом их удаляет задача `media.delete_objects`
с повтором (ADR-0020 §3), а запись получает `purged_at` — «отправлено на удаление». Раз в
час, порциями по CHUNK в своей транзакции (каждая постановка — savepoint, а PostgreSQL
держит в кэше снимка не больше 64 подтранзакций), до LIMIT файлов за запуск: удаление
аккаунтов (2.12) даёт пачки.

Legal hold (ADR-0016 §6): файл — доказательство открытого кейса модерации (2.5a) или спора
(6.1c) — не стирается, а откладывается на HOLD_RECHECK; отложенные не занимают порцию.
"""

from dataclasses import dataclass

from app.modules.media.api import LegalHold
from app.modules.media.application.ports import DELETE_OBJECTS, MediaRepository
from app.modules.media.application.uploads import delete_everything
from app.modules.media.domain.asset import PURGE_AFTER
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.queue.port import JobQueue

CHUNK = 50
LIMIT = 500


@dataclass(frozen=True, slots=True, kw_only=True)
class PurgeDeletedCommand:
    limit: int = LIMIT


class PurgeDeleted:
    def __init__(
        self,
        uow: UnitOfWork,
        assets: MediaRepository,
        hold: LegalHold,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._assets, self._hold = uow, assets, hold
        self._queue, self._clock = queue, clock

    async def __call__(self, cmd: PurgeDeletedCommand) -> int:
        """Сколько файлов отправлено на очистку (удержанные не в счёт)."""
        now = self._clock.now()
        total = purged = 0
        while total < cmd.limit:
            async with self._uow:
                assets = await self._assets.deleted_before(
                    now - PURGE_AFTER, now=now, limit=min(CHUNK, cmd.limit - total)
                )
                held = await self._hold.held([asset.id for asset in assets]) if assets else set()
                for asset in assets:
                    if asset.id in held:
                        asset.hold(now=now)
                        await self._assets.save(asset)
                        continue
                    asset.purge(now=now)
                    await self._assets.save(asset)
                    await self._queue.enqueue(
                        DELETE_OBJECTS, delete_everything(asset), dedup_key=f"purge:{asset.id}"
                    )
                    purged += 1
            total += len(assets)
            if len(assets) < CHUNK:
                break
        return purged
