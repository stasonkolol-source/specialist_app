"""Суточная квота загрузок на Valkey (ARCHITECTURE §13.3): sliding window платформы."""

import math

from app.modules.media.domain.policy import MB
from app.platform.kernel.ids import UserId
from app.platform.ratelimit import Rate, RateLimiter

UPLOAD_MEGABYTES_PER_USER = Rate("media.upload_megabytes", "1024/day")
"""1 GB в сутки: вес загрузки — заявленный размер в мегабайтах с округлением вверх."""


class ValkeyUploadQuota:
    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def charge(self, owner_id: UserId, size_bytes: int) -> None:
        await self._limiter.hit(
            UPLOAD_MEGABYTES_PER_USER, f"user:{owner_id}", cost=math.ceil(size_bytes / MB)
        )
