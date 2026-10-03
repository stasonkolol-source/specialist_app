"""«Показывать после договорённости» (PATCH /me/privacy, S43; DEVELOPMENT_PLAN 6.5): свой Telegram
— второй стороне в сделке и чате сразу после договорённости (по умолчанию да). Телефон — с
подтверждением номера (v1)."""

from dataclasses import dataclass

from app.modules.identity.application.ports import UserRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdatePrivacyCommand:
    actor_id: UserId
    show_telegram: bool | None = None


class UpdatePrivacy:
    def __init__(self, uow: UnitOfWork, users: UserRepository) -> None:
        self._uow, self._users = uow, users

    async def __call__(self, cmd: UpdatePrivacyCommand) -> None:
        async with self._uow:
            user = await self._users.get(cmd.actor_id)
            user.set_privacy(show_telegram=cmd.show_telegram)
            await self._users.save(user)
