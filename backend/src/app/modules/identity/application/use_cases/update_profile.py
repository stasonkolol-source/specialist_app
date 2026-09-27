"""Правка своего профиля: имя и язык интерфейса (PATCH /me)."""

from dataclasses import dataclass

from app.modules.identity.application.ports import UserRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId
from app.platform.kernel.localized import Locale


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateProfileCommand:
    actor_id: UserId
    display_name: str | None = None
    ui_locale: Locale | None = None
    expected_version: int | None = None
    """Из If-Match; None — без сверки."""


class UpdateProfile:
    def __init__(self, uow: UnitOfWork, users: UserRepository, clock: Clock) -> None:
        self._uow, self._users, self._clock = uow, users, clock

    async def __call__(self, cmd: UpdateProfileCommand) -> int:
        """Возвращает новую версию пользователя (ETag)."""
        async with self._uow:
            user = await self._users.get(cmd.actor_id)
            user.ensure_version(cmd.expected_version)
            user.update_profile(
                display_name=cmd.display_name, ui_locale=cmd.ui_locale, now=self._clock.now()
            )
            await self._users.save(user)
        return user.version
