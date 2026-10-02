"""Сверка read-model с источником (периодическая `search.reconcile_index`, ночью; 4.1).

События могли потеряться (сбой воркера), а часть полей меняется без событий: свежесть,
названия районов и категорий. Сверка отмечает к пересборке все опубликованные профили и
все строки индекса — пересборка добавит пропавшие, удалит лишние и обновит остальные.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.search.application.ports import (
    FLUSH_INDEX,
    FlushPayload,
    PendingProfiles,
    SpecialistIndex,
)
from app.modules.search.application.use_cases.mark_profiles import FLUSH_KEY
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.queue.port import JobQueue

PAGE: Final = 1000


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconcileIndexCommand:
    page: int = PAGE
    """Сколько id читать за раз: и опубликованных профилей, и строк индекса."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconcileReport:
    published: int
    indexed: int
    """Сколько строк было в индексе до сверки."""


class ReconcileIndex:
    def __init__(
        self,
        uow: UnitOfWork,
        pending: PendingProfiles,
        index: SpecialistIndex,
        specialists: SpecialistsApi,
        queue: JobQueue,
    ) -> None:
        self._uow, self._pending, self._index = uow, pending, index
        self._specialists, self._queue = specialists, queue

    async def __call__(self, cmd: ReconcileIndexCommand) -> ReconcileReport:
        published = await self._mark_pages(self._published_page, cmd.page)
        indexed = await self._mark_pages(self._indexed_page, cmd.page)
        async with self._uow:
            await self._queue.enqueue(
                FLUSH_INDEX,
                FlushPayload(reason="reconcile"),
                dedup_key=FLUSH_KEY,
            )
        return ReconcileReport(published=published, indexed=indexed)

    async def _published_page(self, after: UUID | None, limit: int) -> list[UUID]:
        return await self._specialists.published_profile_ids(after=after, limit=limit)

    async def _indexed_page(self, after: UUID | None, limit: int) -> list[UUID]:
        return await self._index.ids_after(after, limit=limit)

    async def _mark_pages(
        self, page_of: Callable[[UUID | None, int], Awaitable[list[UUID]]], limit: int
    ) -> int:
        total, after = 0, None
        while page := await page_of(after, limit):
            async with self._uow:
                await self._pending.mark(page, occurred_at=None)
            total += len(page)
            after = page[-1]
        return total
