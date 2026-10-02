"""JsonCache на Valkey: ключи с префиксом `cache:`, значение — JSON (ARCHITECTURE §9.7)."""

import json
from datetime import timedelta

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger(__name__)

PREFIX = "cache:"


class ValkeyJsonCache:
    def __init__(self, valkey: Redis) -> None:
        self._valkey = valkey

    async def get(self, key: str) -> object | None:
        try:
            raw = await self._valkey.get(PREFIX + key)
        except RedisError as exc:
            log.warning("cache_unavailable", op="get", error=type(exc).__name__)
            return None
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: object, *, ttl: timedelta) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        try:
            await self._valkey.set(PREFIX + key, payload, ex=ttl)
        except RedisError as exc:
            log.warning("cache_unavailable", op="set", error=type(exc).__name__)
