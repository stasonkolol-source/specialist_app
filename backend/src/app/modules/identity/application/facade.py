"""Реализация IdentityApi для других модулей (ADR-0020 §6)."""

from app.modules.identity.api import (
    Action,
    IdentityApi,
    RestrictionIn,
    TelegramUserView,
    UserSummary,
)
from app.modules.identity.application.access import AccessChecker
from app.modules.identity.application.ports import IdentityQuery, RestrictionRepository
from app.modules.identity.domain.restriction import Restriction, RestrictionSource
from app.platform.contracts.events.identity import UserRestricted
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import RestrictionId, UserId


class IdentityFacade(IdentityApi):
    def __init__(
        self,
        uow: UnitOfWork,
        query: IdentityQuery,
        restrictions: RestrictionRepository,
        access: AccessChecker,
        clock: Clock,
    ) -> None:
        self._uow, self._query, self._restrictions = uow, query, restrictions
        self._access, self._clock = access, clock

    async def get_user(self, user_id: UserId) -> UserSummary | None:
        return await self._query.user_summary(user_id)

    async def by_telegram(self, telegram_id: int) -> TelegramUserView | None:
        return await self._query.by_telegram(telegram_id)

    async def telegram_chat_id(self, user_id: UserId) -> int | None:
        return await self._query.telegram_chat_id(user_id)

    async def ensure_allowed(self, user_id: UserId, action: Action) -> None:
        await self._access.ensure_allowed(user_id, action)

    async def restrict(self, data: RestrictionIn) -> RestrictionId:
        self._uow.require_active()  # транзакция модерации: решение и санкция — вместе
        now = self._clock.now()
        restriction = Restriction.impose(
            kind=data.kind, reason_code=data.reason_code, ends_at=data.ends_at, now=now
        )
        restriction_id = await self._restrictions.add(
            data.user_id,
            restriction,
            source=RestrictionSource.MODERATION,
            case_id=data.case_id,
            created_by=data.created_by,
        )
        self._uow.add_event(
            UserRestricted(
                user_id=data.user_id,
                restriction_id=restriction_id,
                kind=restriction.kind,
                reason_code=restriction.reason_code,
                until=restriction.ends_at,
                case_id=data.case_id,
                occurred_at=now,
            )
        )
        return restriction_id
