"""Лимит жалоб (ARCHITECTURE §13.3, DSA Art. 23): двадцать в сутки от одного человека. Счётчик —
в Valkey (RateLimiter): превышение попадает в суточные счётчики, по ним — сигнал риска (2.5a)."""

from typing import Final

from app.modules.moderation.domain.reports import DAILY_REPORTS
from app.modules.moderation.errors import ReportsLimitError
from app.platform.kernel.errors import RateLimitedError
from app.platform.kernel.ids import UserId
from app.platform.ratelimit import Rate, RateLimiter, user_subject

REPORTS: Final = Rate("moderation.reports", f"{DAILY_REPORTS}/day")


class ValkeyReportQuota:
    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def take(self, reporter_id: UserId) -> None:
        try:
            await self._limiter.hit(REPORTS, user_subject(reporter_id))
        except RateLimitedError as error:
            raise ReportsLimitError(retry_after=error.retry_after, limit=error.limit) from error
