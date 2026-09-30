"""Пользователь разрешил боту писать (ARCHITECTURE §11.1, ADR-0011, DEVELOPMENT_PLAN 1.4b).

Два входа: `POST /me/telegram/write-access` (Mini App после успешного `requestWriteAccess`)
и подписчик `BotStarted` (`/start` в боте). Адрес — личный чат с ботом: его chat_id даёт
фасад identity (Telegram id живёт там). Повтор идемпотентен. Когда писать стало можно
(канал создан или включён снова) — `WriteAccessGranted` (аналитика, 1.7).
"""

from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.api import IdentityApi
from app.modules.notifications.application.dto import ChannelView
from app.modules.notifications.application.ports import ChannelRepository
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.errors import TelegramNotLinkedError
from app.platform.contracts.events.notifications import WriteAccessGranted
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class GrantTelegramWriteAccessCommand:
    user_id: UserId
    via: GrantedVia
    at: datetime | None = None
    """Когда разрешили (время /start или апдейта Telegram); None — сейчас. Остановку бота
    позже этого момента поздно обработанное разрешение не отменит."""


class GrantTelegramWriteAccess:
    def __init__(
        self, uow: UnitOfWork, channels: ChannelRepository, identity: IdentityApi, clock: Clock
    ) -> None:
        self._uow, self._channels, self._identity, self._clock = uow, channels, identity, clock

    async def __call__(self, cmd: GrantTelegramWriteAccessCommand) -> ChannelView:
        chat_id = await self._identity.telegram_chat_id(cmd.user_id)  # чтение — до транзакции
        if chat_id is None:
            raise TelegramNotLinkedError(user_id=cmd.user_id)
        now = cmd.at or self._clock.now()
        async with self._uow:
            view, granted_now = await self._channels.grant_telegram(
                cmd.user_id, chat_id, via=cmd.via, now=now
            )
            if granted_now:
                self._uow.add_event(
                    WriteAccessGranted(user_id=cmd.user_id, via=cmd.via.value, occurred_at=now)
                )
        return view
