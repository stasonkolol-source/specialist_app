"""Антиспам-лимиты (ARCHITECTURE §13.3): sliding window в Valkey через `limits`.

Лимит — это `Rate` с именем (`auth.ip`, `search.guest`) и окном в синтаксисе limits
(`10/minute`). Субъект — `user:<uuid>` или `ip:<адрес>`. Превышение поднимает
RateLimitedError (HTTP 429, в задаче — повтор) и увеличивает суточный счётчик превышений
субъекта: по нему модерация пишет сигналы риска (шаг 2.5a).

Valkey недоступен — лимит пропускает запрос (fail open) с предупреждением в логе:
антиспам не должен ронять API.
"""

import time
from dataclasses import dataclass, field
from datetime import date
from math import ceil

import structlog
from limits import RateLimitItem, parse
from limits.aio.strategies import SlidingWindowCounterRateLimiter
from limits.errors import StorageError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import RateLimitedError

log = structlog.get_logger(__name__)

EXCEEDED_TTL_SECONDS = 3 * 24 * 3600
"""Счётчики превышений живут трое суток: модерация дочитывает вчерашний день после полуночи."""
USER_SUBJECT = "user:"
"""Префикс субъекта-пользователя: `user:<uuid>`; гость — `ip:<адрес>`."""


def user_subject(user_id: object) -> str:
    return f"{USER_SUBJECT}{user_id}"


def exceeded_key(day: date, subject: str) -> str:
    return f"rl:exceeded:{day:%Y%m%d}:{subject}"


@dataclass(frozen=True, slots=True)
class Rate:
    name: str
    per: str
    item: RateLimitItem = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "item", parse(self.per))

    @property
    def limit(self) -> int:
        return int(self.item.amount)


@dataclass(frozen=True, slots=True)
class RateStatus:
    """Состояние окна после засчитанного действия — для заголовков RateLimit-*."""

    limit: int
    remaining: int
    reset_after: int


class RateLimiter:
    def __init__(
        self, strategy: SlidingWindowCounterRateLimiter, valkey: Redis, clock: Clock
    ) -> None:
        self._strategy = strategy
        self._valkey = valkey
        self._clock = clock

    async def hit(self, rate: Rate, subject: str, *, cost: int = 1) -> RateStatus:
        """Засчитать действие субъекта; сверх лимита — RateLimitedError.

        `cost` — вес действия: квота «1 GB загрузок в сутки» считает мегабайты, а не запросы.
        """
        try:
            allowed = await self._strategy.hit(rate.item, rate.name, subject, cost=cost)
            stats = await self._strategy.get_window_stats(rate.item, rate.name, subject)
        except StorageError as exc:
            log.warning("ratelimit_storage_unavailable", rate=rate.name, error=type(exc).__name__)
            return RateStatus(limit=rate.limit, remaining=rate.limit, reset_after=0)
        reset_after = max(1, ceil(stats.reset_time - time.time()))
        if not allowed:
            await self._count_exceeded(rate, subject)
            log.info("rate_limit_exceeded", rate=rate.name)
            raise RateLimitedError(retry_after=reset_after, limit=rate.limit)
        return RateStatus(limit=rate.limit, remaining=stats.remaining, reset_after=reset_after)

    async def peek(self, rate: Rate, subject: str) -> RateStatus:
        """Состояние окна без засчитанного действия: «сегодня откликов 3 из 50» (S17)."""
        try:
            stats = await self._strategy.get_window_stats(rate.item, rate.name, subject)
        except StorageError as exc:
            log.warning("ratelimit_storage_unavailable", rate=rate.name, error=type(exc).__name__)
            return RateStatus(limit=rate.limit, remaining=rate.limit, reset_after=0)
        reset_after = max(0, ceil(stats.reset_time - time.time()))
        return RateStatus(limit=rate.limit, remaining=stats.remaining, reset_after=reset_after)

    async def exceeded(self, subject: str, day: date) -> dict[str, int]:
        """Превышения субъекта за день по именам лимитов."""
        raw = await self._valkey.hgetall(exceeded_key(day, subject))  # type: ignore[misc]  # redis-py: Awaitable | dict
        return {_text(name): int(count) for name, count in raw.items()}

    async def exceeded_on(self, day: date, *, prefix: str = "") -> dict[str, dict[str, int]]:
        """Превышения всех субъектов за день (`prefix` — `user:` или `ip:`): субъект → лимит
        → сколько 429. Для сигналов риска модерации (2.5a): SCAN по ключам дня, без KEYS.
        RedisError — вызывающему: у периодической задачи свой повтор."""
        head = exceeded_key(day, "")
        found: dict[str, dict[str, int]] = {}
        async for key in self._valkey.scan_iter(match=f"{head}{prefix}*", count=500):
            raw = await self._valkey.hgetall(key)  # type: ignore[misc]  # redis-py: Awaitable | dict
            if raw:
                found[_text(key).removeprefix(head)] = {
                    _text(name): int(count) for name, count in raw.items()
                }
        return found

    async def _count_exceeded(self, rate: Rate, subject: str) -> None:
        key = exceeded_key(self._clock.now().date(), subject)
        try:
            async with self._valkey.pipeline(transaction=True) as pipe:
                pipe.hincrby(key, rate.name, 1)
                pipe.expire(key, EXCEEDED_TTL_SECONDS)
                await pipe.execute()
        except RedisError as exc:
            log.warning("ratelimit_counter_unavailable", rate=rate.name, error=type(exc).__name__)


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value
