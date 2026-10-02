"""Отметить профили к пересборке read-model (подписчики событий, DEVELOPMENT_PLAN 4.1).

Событие называет профиль, пользователя или категории. Профиль пользователя ищется и в
индексе (строка ещё есть, а профиля уже нет), и у specialists (строки ещё нет).
Пересобирает одна задача `search.flush_index` на всех: пока она ждёт, вторая не ставится.
"""

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.modules.search.application.ports import (
    FLUSH_INDEX,
    FlushPayload,
    PendingProfiles,
    SpecialistIndex,
)
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CategoryId, UserId
from app.platform.queue.port import JobQueue

FLUSH_KEY = "flush"


@dataclass(frozen=True, slots=True, kw_only=True)
class MarkProfilesCommand:
    profile_ids: Collection[UUID] = field(default_factory=tuple)
    user_ids: Collection[UserId] = field(default_factory=tuple)
    category_ids: Collection[CategoryId] = field(default_factory=tuple)
    occurred_at: datetime | None = None
    """Когда случилось событие (метрика лага); None — плановая пересборка."""


class MarkProfiles:
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

    async def __call__(self, cmd: MarkProfilesCommand) -> int:
        """Сколько профилей отмечено."""
        ids = set(cmd.profile_ids)
        if cmd.user_ids:
            ids.update(await self._index.ids_of_users(cmd.user_ids))
            for user_id in cmd.user_ids:
                profile = await self._specialists.profile_of(user_id)
                if profile is not None:
                    ids.add(profile.id)
        if cmd.category_ids:
            ids.update(await self._index.ids_with_categories(cmd.category_ids))
        if not ids:
            return 0
        async with self._uow:
            marked = await self._pending.mark(ids, occurred_at=cmd.occurred_at)
            await self._queue.enqueue(FLUSH_INDEX, FlushPayload(), dedup_key=FLUSH_KEY)
        return marked
