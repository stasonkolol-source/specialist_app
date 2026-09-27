"""Кэш конфигурации клиентов и флагов в процессе (TTL 30 с).

Читается из platform.client_config и platform.feature_flags отдельной короткой сессией:
кэш живёт в APP scope и не привязан к запросу. Правка в админке доходит до всех
процессов за TTL, без деплоя. БД недоступна — остаётся прошлый снимок (или пустой),
повторная попытка — через RETRY.
"""

import asyncio
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.platform.config.port import ClientConfigSnapshot, Flag
from app.platform.db.platform_tables import client_config, feature_flags

log = structlog.get_logger(__name__)

TTL = timedelta(seconds=30)
RETRY = timedelta(seconds=5)


class ClientConfigCache:
    def __init__(
        self,
        maker: async_sessionmaker[AsyncSession],
        *,
        ttl: timedelta = TTL,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._maker = maker
        self._ttl = ttl.total_seconds()
        self._monotonic = monotonic
        self._snapshot = ClientConfigSnapshot()
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> ClientConfigSnapshot:
        if self._monotonic() < self._expires:
            return self._snapshot
        async with self._lock:
            if self._monotonic() >= self._expires:
                await self._refresh()
        return self._snapshot

    def invalidate(self) -> None:
        self._expires = 0.0

    async def is_enabled(self, key: str) -> bool:
        flag = (await self.get()).flags.get(key)
        return flag is not None and flag.enabled

    async def value(self, key: str) -> object | None:
        flag = (await self.get()).flags.get(key)
        return flag.value if flag is not None and flag.enabled else None

    async def _refresh(self) -> None:
        try:
            async with self._maker() as session:
                config = {
                    row.key: row.value
                    for row in await session.execute(
                        select(client_config.c.key, client_config.c.value)
                    )
                }
                flags = {
                    row.key: Flag(enabled=row.enabled, value=row.value, public=row.public)
                    for row in await session.execute(
                        select(
                            feature_flags.c.key,
                            feature_flags.c.enabled,
                            feature_flags.c.value,
                            feature_flags.c.public,
                        )
                    )
                }
        except (SQLAlchemyError, OSError) as exc:
            log.warning("client_config_unavailable", error=type(exc).__name__)
            self._expires = self._monotonic() + RETRY.total_seconds()
            return
        self._snapshot = ClientConfigSnapshot(
            min_versions=_strings(config.get("min_versions")),
            legal_versions=_strings(config.get("legal_versions")),
            flags=flags,
        )
        self._expires = self._monotonic() + self._ttl


def _strings(value: Any) -> dict[str, str]:
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}
