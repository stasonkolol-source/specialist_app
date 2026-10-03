"""Снимок справочника в памяти процесса (перф-аудит 2026-10): города, районы, категории.

Справочники меняются импортом сидов и админкой, а читаются почти каждым экраном — BFF зовут их
по нескольку раз за запрос. Снимок читается целиком отдельной короткой сессией и живёт в APP
scope до TTL, как кэш client-config и словарь модерации. Пока один запрос обновляет снимок,
остальные отдают прошлый, не дожидаясь (stale-while-refresh); первый снимок ждут все. База
недоступна — остаётся прошлый снимок, повтор через RETRY; снимка ещё нет — ошибка вызывающему,
как без кэша.

Производные представления (тело ответа с ETag на язык) снимок запоминает у себя (`memo`).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.platform.cache.memo import Memo

log = structlog.get_logger(__name__)

RETRY = timedelta(seconds=5)


class Snapshot[T]:
    """Данные одного обновления и представления, построенные из них."""

    def __init__(self, data: T) -> None:
        self.data = data
        self.memo = Memo()


class SnapshotCache[T]:
    def __init__(
        self,
        maker: async_sessionmaker[AsyncSession],
        load: Callable[[AsyncSession], Awaitable[T]],
        *,
        name: str,
        ttl: timedelta,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._maker, self._load, self._name = maker, load, name
        self._ttl, self._monotonic = ttl.total_seconds(), monotonic
        self._snapshot: Snapshot[T] | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> Snapshot[T]:
        snapshot = self._snapshot
        if snapshot is not None and (self._monotonic() < self._expires or self._lock.locked()):
            return snapshot  # свежий — или его обновляет другой запрос: прошлый, без ожидания
        async with self._lock:
            if self._snapshot is None or self._monotonic() >= self._expires:
                return await self._refresh()
            return self._snapshot

    def invalidate(self) -> None:
        """Импорт сидов в этом процессе: следующий запрос перечитает справочник."""
        self._expires = 0.0

    async def _refresh(self) -> Snapshot[T]:
        try:
            async with self._maker() as session:
                data = await self._load(session)
        except (SQLAlchemyError, OSError) as exc:
            if self._snapshot is None:
                raise
            log.warning("snapshot_refresh_failed", cache=self._name, error=type(exc).__name__)
            self._expires = self._monotonic() + RETRY.total_seconds()
            return self._snapshot
        self._snapshot = Snapshot(data)
        self._expires = self._monotonic() + self._ttl
        return self._snapshot


__all__ = ["Snapshot", "SnapshotCache"]
