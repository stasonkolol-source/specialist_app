"""Суточная квота новых заявок на Valkey (ARCHITECTURE §13.3): sliding window платформы.

Уровни доверия 0–1 — пять новых заявок в сутки, проверенные (≥ 2) — двадцать. Сверх —
DailyJobsLimitError (429 с Retry-After); систематическое превышение платформа пишет в сигналы
риска модерации.
"""

from app.modules.jobs.errors import DailyJobsLimitError
from app.platform.kernel.errors import RateLimitedError
from app.platform.kernel.ids import UserId
from app.platform.ratelimit import Rate, RateLimiter, user_subject

NEW_JOBS = Rate("jobs.new_per_day", "5/day")
NEW_JOBS_TRUSTED = Rate("jobs.new_per_day_trusted", "20/day")


class ValkeyJobQuota:
    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def take(self, client_id: UserId, *, trusted: bool) -> None:
        rate = NEW_JOBS_TRUSTED if trusted else NEW_JOBS
        try:
            await self._limiter.hit(rate, user_subject(client_id))
        except RateLimitedError as error:
            raise DailyJobsLimitError(retry_after=error.retry_after, limit=error.limit) from error
