"""Суточные квоты новых заявок и откликов на Valkey (ARCHITECTURE §13.3): sliding window
платформы.

Заявки: уровни доверия 0–1 — пять в сутки, проверенные (≥ 2) — двадцать. Отклики: десять и
пятьдесят. Сверх — 429 с Retry-After (DailyJobsLimitError, DailyResponsesLimitError);
систематическое превышение платформа пишет в сигналы риска модерации.
"""

from app.modules.jobs.application.responses import TodayQuota
from app.modules.jobs.errors import DailyJobsLimitError, DailyResponsesLimitError
from app.platform.kernel.errors import RateLimitedError
from app.platform.kernel.ids import UserId
from app.platform.ratelimit import Rate, RateLimiter, user_subject

NEW_JOBS = Rate("jobs.new_per_day", "5/day")
NEW_JOBS_TRUSTED = Rate("jobs.new_per_day_trusted", "20/day")
RESPONSES = Rate("jobs.responses_per_day", "10/day")
RESPONSES_TRUSTED = Rate("jobs.responses_per_day_trusted", "50/day")


class ValkeyJobQuota:
    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def take(self, client_id: UserId, *, trusted: bool) -> None:
        rate = NEW_JOBS_TRUSTED if trusted else NEW_JOBS
        try:
            await self._limiter.hit(rate, user_subject(client_id))
        except RateLimitedError as error:
            raise DailyJobsLimitError(retry_after=error.retry_after, limit=error.limit) from error


class ValkeyResponseQuota:
    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def take(self, performer_id: UserId, *, trusted: bool) -> None:
        rate = RESPONSES_TRUSTED if trusted else RESPONSES
        try:
            await self._limiter.hit(rate, user_subject(performer_id))
        except RateLimitedError as error:
            raise DailyResponsesLimitError(
                retry_after=error.retry_after, limit=error.limit
            ) from error

    async def today(self, performer_id: UserId, *, trusted: bool) -> TodayQuota:
        rate = RESPONSES_TRUSTED if trusted else RESPONSES
        status = await self._limiter.peek(rate, user_subject(performer_id))
        return TodayQuota(used=max(0, status.limit - status.remaining), limit=status.limit)
