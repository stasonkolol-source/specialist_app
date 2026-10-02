"""Пользователь из бота: /start создаёт аккаунт тем же кодом, что и вход Mini App (0.22).

Сессия и токены боту не нужны: бот узнаёт пользователя по `from.id` на каждом апдейте.
Параллельные /start одного человека (двойное нажатие, апдейты после простоя) идут по
очереди: вход блокирует строку пользователя, а гонку двух первых регистраций решает
повтор. Каждый /start публикует `BotStarted`: Telegram теперь разрешает боту писать первым, и
notifications открывает канал доставки (1.4b). Фасад notifications identity вызвать не
может — он выше по DAG (ARCHITECTURE §5.4), поэтому только событие.
"""

from dataclasses import dataclass

from app.modules.identity.api import TelegramUserView
from app.modules.identity.application.config import IdentityConfig
from app.modules.identity.application.dto import TelegramProfile
from app.modules.identity.application.ports import (
    DeletedIdentities,
    IdentityQuery,
    UserRepository,
)
from app.modules.identity.application.telegram import sign_in_telegram
from app.modules.identity.domain.user import User
from app.platform.contracts.events.identity import BotStarted, EntryPoint
from app.platform.db.port import UnitOfWork
from app.platform.db.retry import retry_on_conflict
from app.platform.kernel.clock import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisterTelegramUserCommand:
    profile: TelegramProfile
    start_param: str | None = None
    """Payload `/start <payload>` — код deep link `t.me/<bot>?start=` (первое касание)."""


class RegisterTelegramUser:
    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        query: IdentityQuery,
        deleted: DeletedIdentities,
        config: IdentityConfig,
        clock: Clock,
    ) -> None:
        self._uow, self._users, self._query = uow, users, query
        self._deleted, self._config, self._clock = deleted, config, clock

    async def __call__(self, cmd: RegisterTelegramUserCommand) -> tuple[TelegramUserView, bool]:
        """(пользователь, создан ли сейчас)."""
        now = self._clock.now()

        async def attempt() -> tuple[User, bool]:
            async with self._uow:
                user, is_new = await sign_in_telegram(
                    self._users,
                    self._query,
                    self._deleted,
                    cmd.profile,
                    now,
                    hash_key=self._config.hash_key,
                    entry_point=EntryPoint.BOT,
                    start_param=cmd.start_param,
                )
                # состояние агрегата не меняется: факт «написал боту» — событие без агрегата
                self._uow.add_event(BotStarted(user_id=user.id, occurred_at=now))
            return user, is_new

        # накопившиеся /start polling отдаёт разом, и aiogram обрабатывает их параллельно:
        # два первых /start создают пользователя одновременно — второй повторяет и входит
        user, is_new = await retry_on_conflict(attempt)
        return (
            TelegramUserView(
                id=user.id,
                display_name=user.display_name,
                ui_locale=user.ui_locale,
                trust_level=user.trust_level,
            ),
            is_new,
        )
