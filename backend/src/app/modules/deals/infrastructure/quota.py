"""Суточный лимит споров на Valkey (ARCHITECTURE §13.3): sliding window платформы.

Спор будит вторую сторону уведомлением P0: открыть, отозвать и открыть снова — не спам, но больше
пяти в сутки — уже он. Считаются только открытые споры: use case берёт квоту, когда спор уже
прошёл все проверки (MU-9) — отказы 404 и 409 лимит не тратят.
"""

from app.modules.deals.errors import DailyDisputesLimitError
from app.platform.kernel.errors import RateLimitedError
from app.platform.kernel.ids import UserId
from app.platform.ratelimit import Rate, RateLimiter, user_subject

DISPUTES = Rate("deals.disputes", "5/day")
"""Имя — как у прежнего лимита маршрута: счётчики окна на выкладке не обнуляются."""


class ValkeyDisputeQuota:
    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def take(self, user_id: UserId) -> None:
        try:
            await self._limiter.hit(DISPUTES, user_subject(user_id))
        except RateLimitedError as error:
            raise DailyDisputesLimitError(
                retry_after=error.retry_after, limit=error.limit
            ) from error
