"""Фейки фасадов других модулей для тестов notifications (ADR-0020 §11)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.modules.identity.api import Action, RestrictionIn, TelegramUserView, UserSummary
from app.platform.kernel.ids import RestrictionId, UserId
from app.platform.kernel.localized import Locale


@dataclass
class FakeIdentity:
    """IdentityApi: личные чаты и язык пользователей задаёт тест; остальное notifications
    не нужно."""

    chats: dict[UserId, int] = field(default_factory=dict)
    locales: dict[UserId, Locale] = field(default_factory=dict)
    deleted: set[UserId] = field(default_factory=set)

    async def get_user(self, user_id: UserId) -> UserSummary | None:
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
