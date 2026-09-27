"""Схемы HTTP notifications (ADR-0020 §10: <Имя>In / <Имя>Out)."""

from datetime import datetime

from pydantic import BaseModel

from app.modules.notifications.application.dto import ChannelView
from app.modules.notifications.domain.channel import GrantedVia


class TelegramChannelOut(BaseModel):
    """Канал «бот пишет в личный чат»: Mini App решает, просить ли разрешение (S21, S02c)."""

    writable: bool
    """Бот может писать пользователю; false — бот заблокирован (шаг 2.3)."""
    granted_via: GrantedVia
    """Как получено разрешение: `bot_start` — /start в боте, `mini_app` — requestWriteAccess."""
    granted_at: datetime

    @classmethod
    def of(cls, view: ChannelView) -> TelegramChannelOut:
        return cls(writable=view.writable, granted_via=view.granted_via, granted_at=view.granted_at)
