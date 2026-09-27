"""Результаты use cases notifications (ADR-0020 §3)."""

from dataclasses import dataclass
from datetime import datetime

from app.modules.notifications.domain.channel import ChannelKind, GrantedVia


@dataclass(frozen=True, slots=True, kw_only=True)
class ChannelView:
    """Состояние канала для пользователя; адрес доставки (chat_id) наружу не отдаём."""

    kind: ChannelKind
    granted_via: GrantedVia
    granted_at: datetime
    """Когда доставка разрешена; повтор при доступном канале время не меняет."""
    disabled_at: datetime | None = None
    """Доставка не проходит (бот заблокирован — 403, шаг 2.3); None — канал доступен."""

    @property
    def writable(self) -> bool:
        return self.disabled_at is None
