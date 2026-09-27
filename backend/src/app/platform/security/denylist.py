"""Denylist сессий в Valkey (ADR-0009): немедленный отзыв access-токенов.

Бан или выход кладёт `sid` сюда на время жизни access-токена; проверка Bearer (0.15b)
отвергает токены отозванной сессии, не дожидаясь их истечения. Refresh отзывается
в БД — отдельно.
"""

from datetime import timedelta

from redis.asyncio import Redis


def _key(session_id: str) -> str:
    return f"auth:revoked:{session_id}"


class SessionDenylist:
    def __init__(self, valkey: Redis, *, ttl: timedelta) -> None:
        self._valkey = valkey
        self._ttl = ttl

    async def revoke(self, session_id: str) -> None:
        await self._valkey.set(_key(session_id), b"1", ex=self._ttl)

    async def is_revoked(self, session_id: str) -> bool:
        return bool(await self._valkey.exists(_key(session_id)))
