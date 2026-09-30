"""Счётчики velocity в Valkey (domain/velocity.py): множество на отпечаток текста.

SADD, EXPIRE NX и SCARD — одной транзакцией: окно считается с первого добавления, повтор
того же участника (повторная проверка) ничего не меняет. Valkey недоступен — None: правило
пропускается с предупреждением в логе (fail open, как у лимитов §13.3).
"""

from datetime import timedelta

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

PREFIX = "mod:vel:"


class ValkeyVelocityCounter:
    def __init__(self, valkey: Redis, *, prefix: str = PREFIX) -> None:
        self._valkey, self._prefix = valkey, prefix

    async def add(self, key: str, member: str, *, window: timedelta) -> int | None:
        name = self._prefix + key
        try:
            async with self._valkey.pipeline(transaction=True) as pipe:
                pipe.sadd(name, member)
                pipe.expire(name, int(window.total_seconds()), nx=True)
                pipe.scard(name)
                *_, count = await pipe.execute()
        except RedisError as exc:
            log.warning("velocity_unavailable", error=type(exc).__name__)
            return None
        return int(count)
