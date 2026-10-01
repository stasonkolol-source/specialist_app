"""Превышения антиспам-лимитов пользователями — из счётчиков platform/ratelimit.py (0.13b)."""

from collections.abc import Mapping
from datetime import date
from uuid import UUID

import structlog
from redis.exceptions import RedisError

from app.platform.kernel.ids import UserId
from app.platform.ratelimit import USER_SUBJECT, RateLimiter

log = structlog.get_logger(__name__)


class ValkeyRateLimitOverflows:
    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def by_user(self, day: date) -> Mapping[UserId, Mapping[str, int]]:
        try:
            found = await self._limiter.exceeded_on(day, prefix=USER_SUBJECT)
        except RedisError as exc:
            # антиспам не должен падать: сигналы досчитает следующий запуск (счётчики живут 3 дня)
            log.warning("rate_limit_overflows_unavailable", error=type(exc).__name__)
            return {}
        overflows: dict[UserId, Mapping[str, int]] = {}
        for subject, exceeded in found.items():
            try:
                overflows[UserId(UUID(subject.removeprefix(USER_SUBJECT)))] = exceeded
            except ValueError:
                log.warning("rate_limit_subject_unknown")
        return overflows
