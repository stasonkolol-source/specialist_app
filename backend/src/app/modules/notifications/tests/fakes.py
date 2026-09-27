"""Фейки фасадов других модулей для тестов notifications (ADR-0020 §11)."""

from dataclasses import dataclass, field

from app.modules.identity.api import Action, RestrictionIn, TelegramUserView, UserSummary
from app.platform.kernel.ids import RestrictionId, UserId


@dataclass
class FakeIdentity:
    """IdentityApi: личные чаты пользователей задаёт тест; остальное notifications не нужно."""

    chats: dict[UserId, int] = field(default_factory=dict)

    async def get_user(self, user_id: UserId) -> UserSummary | None:
        return None

    async def by_telegram(self, telegram_id: int) -> TelegramUserView | None:
        return None

    async def telegram_chat_id(self, user_id: UserId) -> int | None:
        return self.chats.get(user_id)

    async def ensure_allowed(self, user_id: UserId, action: Action) -> None:
        return None

    async def restrict(self, data: RestrictionIn) -> RestrictionId:
        raise NotImplementedError
