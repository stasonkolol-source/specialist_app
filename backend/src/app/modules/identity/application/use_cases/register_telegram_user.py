"""Пользователь из бота: /start создаёт аккаунт тем же кодом, что и вход Mini App (0.22).

Сессия и токены боту не нужны: бот узнаёт пользователя по `from.id` на каждом апдейте.
Каждый /start публикует `BotStarted`: Telegram теперь разрешает боту писать первым, и
notifications открывает канал доставки (1.4b). Фасад notifications identity вызвать не
может — он выше по DAG (ARCHITECTURE §5.4), поэтому только событие.
"""

from dataclasses import dataclass

from app.modules.identity.api import TelegramUserView
from app.modules.identity.application.dto import TelegramProfile
from app.modules.identity.application.ports import IdentityQuery, UserRepository
from app.modules.identity.application.telegram import sign_in_telegram
from app.platform.contracts.events.identity import BotStarted, EntryPoint
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisterTelegramUserCommand:
    profile: TelegramProfile
    start_param: str | None = None
    """Payload `/start <payload>` — код deep link `t.me/<bot>?start=` (первое касание)."""


class RegisterTelegramUser:
    def __init__(
        self, uow: UnitOfWork, users: UserRepository, query: IdentityQuery, clock: Clock
    ) -> None:
        self._uow, self._users, self._query, self._clock = uow, users, query, clock

    async def __call__(self, cmd: RegisterTelegramUserCommand) -> tuple[TelegramUserView, bool]:
        """(пользователь, создан ли сейчас)."""
        now = self._clock.now()
        async with self._uow:
            user, is_new = await sign_in_telegram(
                self._users,
                self._query,
                cmd.profile,
                now,
                entry_point=EntryPoint.BOT,
                start_param=cmd.start_param,
            )
            # состояние агрегата не меняется: факт «написал боту» — событие без агрегата
            self._uow.add_event(BotStarted(user_id=user.id, occurred_at=now))
        return (
            TelegramUserView(
                id=user.id,
                display_name=user.display_name,
                ui_locale=user.ui_locale,
                trust_level=user.trust_level,
            ),
            is_new,
        )
