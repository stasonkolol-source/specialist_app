"""Лимиты переписки (ARCHITECTURE §13.3): сообщений в час — 20 у уровней 0–1 и 100 у
проверенных, новых диалогов — не больше пяти в час. Счётчики — в Valkey (RateLimiter)."""

from typing import Final

from app.modules.messaging.errors import ConversationsLimitError, MessagesLimitError
from app.platform.kernel.errors import RateLimitedError
from app.platform.kernel.ids import UserId
from app.platform.ratelimit import Rate, RateLimiter, user_subject

MESSAGES: Final = Rate("messaging.messages", "20/hour")
MESSAGES_TRUSTED: Final = Rate("messaging.messages_trusted", "100/hour")
CONVERSATIONS: Final = Rate("messaging.conversations", "5/hour")


class ValkeyMessageQuota:
    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def take_message(self, user_id: UserId, *, trusted: bool) -> None:
        try:
            await self._limiter.hit(
                MESSAGES_TRUSTED if trusted else MESSAGES, user_subject(user_id)
            )
        except RateLimitedError as error:
            raise MessagesLimitError(retry_after=error.retry_after, limit=error.limit) from error

    async def take_conversation(self, user_id: UserId) -> None:
        try:
            await self._limiter.hit(CONVERSATIONS, user_subject(user_id))
        except RateLimitedError as error:
            raise ConversationsLimitError(
                retry_after=error.retry_after, limit=error.limit
            ) from error
