"""Пользователь остановил бота (`my_chat_member` → `kicked`, ARCHITECTURE §11.1, ADR-0011).

Канал telegram выключается сразу, а не при первой неудачной отправке: уведомления не
тратят попытки на 403, а в центре уведомлений они остаются. Снова включают канал /start
и `my_chat_member` → `member` (GrantTelegramWriteAccess). Повтор ничего не меняет.
"""

from dataclasses import dataclass
from datetime import datetime

from app.modules.notifications.application.ports import ChannelRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class BlockTelegramChannelCommand:
    user_id: UserId
    at: datetime
    """Когда человек остановил бота (дата апдейта Telegram): разрешение новее — действует
    оно, а поздно обработанная остановка канал не выключит."""


class BlockTelegramChannel:
    def __init__(self, uow: UnitOfWork, channels: ChannelRepository) -> None:
        self._uow, self._channels = uow, channels

    async def __call__(self, cmd: BlockTelegramChannelCommand) -> bool:
        """Выключен ли канал сейчас; False — выключать было нечего."""
        async with self._uow:
            return await self._channels.disable_telegram(cmd.user_id, at=cmd.at)
