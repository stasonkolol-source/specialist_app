"""Счётчики velocity в Valkey (domain/velocity.py): множество на отпечаток текста.

SADD, EXPIRE NX и SCARD — одной транзакцией: окно считается с первого добавления, повтор
того же участника (повторная проверка) ничего не меняет. Valkey недоступен или не ответил
за TIMEOUT — None: правило пропускается с предупреждением в логе (fail open, как у лимитов
§13.3). Таймаут свой: у общего клиента Valkey его нет, и зависший Valkey подвесил бы проверку.
"""

import asyncio
from datetime import timedelta

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

PREFIX = "mod:vel:"
TIMEOUT = 0.5
"""Секунды на ответ Valkey: счётчик — подсказка модерации, ждать его дольше незачем."""


class ValkeyVelocityCounter:
    def __init__(self, valkey: Redis, *, prefix: str = PREFIX) -> None:
        self._valkey, self._prefix = valkey, prefix

    async def add(self, key: str, member: str, *, window: timedelta) -> int | None:
        name = self._prefix + key
        try:
            async with asyncio.timeout(TIMEOUT), self._valkey.pipeline(transaction=True) as pipe:
                pipe.sadd(name, member)
                pipe.expire(name, int(window.total_seconds()), nx=True)
                pipe.scard(name)
                *_, count = await pipe.execute()
        except (RedisError, TimeoutError) as exc:
            log.warning("velocity_unavailable", error=type(exc).__name__)
            return None
        return int(count)
