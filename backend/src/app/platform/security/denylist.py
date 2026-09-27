"""Denylist сессий в Valkey (ADR-0009): немедленный отзыв access-токенов.

Бан или выход кладёт `sid` сюда на время жизни access-токена; проверка Bearer отвергает
токены отозванной сессии, не дожидаясь их истечения. Refresh отзывается в БД — отдельно.

Valkey недоступен — проверка пропускает токен с предупреждением: отзыв запоздает не
больше чем на срок access (15 минут), а API продолжит работать.
"""

from datetime import timedelta

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)


def _key(session_id: str) -> str:
    return f"auth:revoked:{session_id}"


class SessionDenylist:
    def __init__(self, valkey: Redis, *, ttl: timedelta) -> None:
        self._valkey = valkey
        self._ttl = ttl

    async def revoke(self, session_id: str) -> None:
        await self._valkey.set(_key(session_id), b"1", ex=self._ttl)

    async def is_revoked(self, session_id: str) -> bool:
        try:
            return bool(await self._valkey.exists(_key(session_id)))
        except RedisError as exc:
            log.warning("denylist_unavailable", error=type(exc).__name__)
            return False
