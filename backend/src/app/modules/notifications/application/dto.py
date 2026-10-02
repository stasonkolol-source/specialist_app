"""Результаты use cases notifications (ADR-0020 §3)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.notifications.domain.catalog import NotificationType, Priority
from app.modules.notifications.domain.channel import ChannelKind, GrantedVia
from app.modules.notifications.domain.notification import (
    DeliveryId,
    DeliveryStatus,
    NotificationId,
)
from app.modules.notifications.domain.settings import NotificationSettings
from app.platform.kernel.ids import UserId
from app.platform.kernel.pagination import Page


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


@dataclass(frozen=True, slots=True, kw_only=True)
class NewNotification:
    user_id: UserId
    type: NotificationType
    dedupe_key: str
    params: Mapping[str, str]
    link: str | None
    urgent: bool
    priority: Priority
    in_app: bool
    valid_until: datetime | None = None
    """Позже — сообщение уже неправда: доставка в бот не уходит («закроется через 2 ч»)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TelegramTarget:
    """Куда доставлять в Telegram: строка канала и доступен ли он."""

    channel_id: UUID
    writable: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationRecord:
    """Уведомление центра как есть: текст собирается на языке читателя."""

    id: NotificationId
    type: NotificationType
    params: Mapping[str, str]
    link: str | None
    created_at: datetime
    read_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderedText:
    title: str
    body: str


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationView:
    """Строка центра уведомлений (S42) на языке запроса."""

    id: NotificationId
    type: NotificationType
    title: str
    body: str
    link: str | None
    """Код deep link (ARCHITECTURE §11.4): куда ведёт нажатие."""
    created_at: datetime
    read: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationFeed:
    page: Page[NotificationView]
    unread: int


@dataclass(frozen=True, slots=True, kw_only=True)
class DeliveryTarget:
    """Доставка, готовая к отправке: что, кому и куда."""

    id: DeliveryId
    status: DeliveryStatus
    not_before: datetime
    user_id: UserId
    channel_id: UUID
    chat_id: int
    """Личный чат с ботом. Не логируется (ADR-0020 §14)."""
    writable: bool
    type: NotificationType
    params: Mapping[str, str]
    link: str | None
    urgent: bool
    """Срочное (заявка `asap`): тихие часы не действуют."""
    valid_until: datetime | None = None
    """Позже этого момента не отправлять: доставка `suppressed`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SettingsView:
    settings: NotificationSettings
    telegram: ChannelView | None
    """Канал бота; None — пользователь ещё не разрешил боту писать."""
