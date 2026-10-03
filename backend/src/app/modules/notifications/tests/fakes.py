"""Фейки фасадов других модулей для тестов notifications (ADR-0020 §11)."""

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.modules.identity.api import (
    Action,
    BlockedUser,
    BlockSide,
    RestrictionIn,
    TelegramUserView,
    UserSummary,
)
from app.platform.kernel.ids import CaseId, RestrictionId, UserId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Role


@dataclass
class FakeIdentity:
    """IdentityApi: личные чаты и язык пользователей задаёт тест; остальное notifications
    не нужно."""

    chats: dict[UserId, int] = field(default_factory=dict)
    locales: dict[UserId, Locale] = field(default_factory=dict)
    deleted: set[UserId] = field(default_factory=set)

    async def get_user(
        self, user_id: UserId, *, viewer_id: UserId | None = None
    ) -> UserSummary | None:
        if user_id not in self.locales:
            return None
        return UserSummary(
            id=user_id,
            display_name="Ana",
            ui_locale=self.locales[user_id],
            trust_level=0,
            phone_verified=False,
            is_deleted=user_id in self.deleted,
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
        )

    async def users(
        self, user_ids: Collection[UserId], *, viewer_id: UserId | None = None
    ) -> dict[UserId, UserSummary]:
        found = {user_id: await self.get_user(user_id) for user_id in user_ids}
        return {user_id: user for user_id, user in found.items() if user is not None}

    async def telegram_contacts(self, user_ids: Collection[UserId]) -> dict[UserId, str]:
        return {}

    async def by_telegram(self, telegram_id: int) -> TelegramUserView | None:
        return None

    async def telegram_chat_id(self, user_id: UserId) -> int | None:
        return self.chats.get(user_id)

    async def ensure_allowed(self, user_id: UserId, action: Action) -> None:
        return None

    async def restrict(self, data: RestrictionIn) -> RestrictionId:
        raise NotImplementedError

    async def record_violation(self, user_id: UserId) -> None:
        raise NotImplementedError

    async def roles(self, user_id: UserId) -> frozenset[Role]:
        return frozenset()

    async def lift_case_restrictions(self, case_id: CaseId) -> int:
        raise NotImplementedError

    async def hidden_from_search(
        self, user_ids: Collection[UserId]
    ) -> dict[UserId, datetime | None]:
        raise NotImplementedError

    async def blocked_ids(self, user_id: UserId) -> frozenset[UserId]:
        return frozenset()

    async def blocks_with(
        self, user_id: UserId, others: Collection[UserId]
    ) -> dict[UserId, BlockSide]:
        return {}

    async def blocked_users(self, user_id: UserId) -> list[BlockedUser]:
        return []
