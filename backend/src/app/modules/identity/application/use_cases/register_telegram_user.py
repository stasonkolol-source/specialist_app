"""Пользователь из бота: /start создаёт аккаунт тем же кодом, что и вход Mini App (0.22).

Сессия и токены боту не нужны: бот узнаёт пользователя по `from.id` на каждом апдейте.
"""

from dataclasses import dataclass

from app.modules.identity.api import TelegramUserView
from app.modules.identity.application.dto import TelegramProfile
from app.modules.identity.application.ports import IdentityQuery, UserRepository
from app.modules.identity.application.telegram import sign_in_telegram
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisterTelegramUserCommand:
    profile: TelegramProfile


class RegisterTelegramUser:
    def __init__(
        self, uow: UnitOfWork, users: UserRepository, query: IdentityQuery, clock: Clock
    ) -> None:
        self._uow, self._users, self._query, self._clock = uow, users, query, clock

    async def __call__(self, cmd: RegisterTelegramUserCommand) -> tuple[TelegramUserView, bool]:
        """(пользователь, создан ли сейчас)."""
        async with self._uow:
            user, is_new = await sign_in_telegram(
                self._users, self._query, cmd.profile, self._clock.now()
            )
        return (
            TelegramUserView(
                id=user.id,
                display_name=user.display_name,
                ui_locale=user.ui_locale,
                trust_level=user.trust_level,
            ),
            is_new,
        )
