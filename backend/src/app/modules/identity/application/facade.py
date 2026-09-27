"""Реализация IdentityApi для других модулей (ADR-0020 §6)."""

from app.modules.identity.api import Action, IdentityApi, TelegramUserView, UserSummary
from app.modules.identity.application.access import ensure_allowed
from app.modules.identity.application.ports import IdentityQuery
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


class IdentityFacade(IdentityApi):
    def __init__(self, query: IdentityQuery, clock: Clock) -> None:
        self._query = query
        self._clock = clock

    async def get_user(self, user_id: UserId) -> UserSummary | None:
        return await self._query.user_summary(user_id)

    async def by_telegram(self, telegram_id: int) -> TelegramUserView | None:
        return await self._query.by_telegram(telegram_id)

    async def ensure_allowed(self, user_id: UserId, action: Action) -> None:
        now = self._clock.now()
        ensure_allowed(await self._query.restrictions(user_id, now), action, now)
