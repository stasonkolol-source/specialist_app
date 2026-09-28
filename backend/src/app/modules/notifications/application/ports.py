"""Порты модуля notifications (ADR-0020 §3, §5)."""

from datetime import datetime
from typing import Final, Protocol

from app.modules.notifications.application.dto import ChannelView
from app.modules.notifications.domain.channel import GrantedVia
from app.platform.contracts.events.identity import BotStarted
from app.platform.kernel.ids import UserId
from app.platform.queue.port import TaskRef


class ChannelRepository(Protocol):
    """Каналы доставки — простая запись (ADR-0020 §5)."""

    async def grant_telegram(
        self, user_id: UserId, chat_id: int, *, via: GrantedVia, now: datetime
    ) -> tuple[ChannelView, bool]:
        """Канал telegram доступен: создать или включить выключенный.

        Уже доступный канал не меняется — повтор идемпотентен. Второе значение — стал ли
        канал доступным сейчас (создан или включён): False у повтора. Нужен активный UoW.
        """
        ...


GRANT_WRITE_ACCESS: Final = TaskRef("notifications.grant_write_access", BotStarted)
"""Подписчик BotStarted: /start разрешает боту писать — канал telegram доступен."""
