"""Порты модуля notifications (ADR-0020 §3, §5)."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from app.modules.notifications.application.dto import (
    ChannelView,
    DeliveryTarget,
    NewNotification,
    NotificationRecord,
    RenderedText,
    TelegramTarget,
)
from app.modules.notifications.domain.catalog import NotificationType
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.domain.notification import (
    DeliveryId,
    DeliveryStatus,
    NotificationId,
)
from app.modules.notifications.domain.settings import NotificationSettings
from app.platform.contracts.events.identity import BotStarted, UserRestricted
from app.platform.contracts.events.moderation import ModerationDecisionMade
from app.platform.kernel.ids import UserId
from app.platform.kernel.localized import Locale
from app.platform.kernel.pagination import Page, PageRequest
from app.platform.queue.port import TaskRef
from app.platform.telegram.port import AppButton


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

    async def telegram_target(self, user_id: UserId) -> TelegramTarget | None:
        """Канал telegram пользователя; None — боту писать не разрешали. Нужен активный UoW."""
        ...


class NotificationRepository(Protocol):
    """Уведомления и доставки — простые записи (ADR-0020 §5). Нужен активный UoW."""

    async def add(self, notification: NewNotification) -> NotificationId | None:
        """Записать уведомление; None — `dedupe_key` уже был (повтор события)."""
        ...

    async def add_delivery(
        self, notification_id: NotificationId, channel_id: UUID, *, not_before: datetime
    ) -> DeliveryId:
        """Доставка в канал в статусе `queued`."""
        ...

    async def postpone_delivery(self, delivery_id: DeliveryId, *, not_before: datetime) -> bool:
        """Сдвинуть `not_before` доставки в `queued`; False — уже не `queued`."""
        ...

    async def settle_delivery(
        self,
        delivery_id: DeliveryId,
        status: DeliveryStatus,
        *,
        now: datetime,
        provider_message_id: str | None = None,
        error: str | None = None,
    ) -> bool:
        """`queued` → итог; False — доставка уже не `queued` (повтор задачи)."""
        ...

    async def mark_read(
        self, user_id: UserId, ids: Collection[NotificationId] | None, *, now: datetime
    ) -> int:
        """Отметить прочитанными свои уведомления центра (None — все); сколько отмечено."""
        ...


class SettingsRepository(Protocol):
    """Настройки уведомлений — простая запись. Нужен активный UoW."""

    async def load(self, user_id: UserId) -> NotificationSettings: ...

    async def save(self, user_id: UserId, settings: NotificationSettings) -> None:
        """Заменить выбор «группа × канал», тихие часы и час дайджеста."""
        ...


class NotificationQuery(Protocol):
    """Чтение без блокировок (ADR-0020 §4)."""

    async def page(self, user_id: UserId, request: PageRequest) -> Page[NotificationRecord]:
        """Центр уведомлений: новые сверху, курсор по id (UUIDv7)."""
        ...

    async def unread(self, user_id: UserId) -> int: ...

    async def delivery(self, delivery_id: DeliveryId) -> DeliveryTarget | None: ...

    async def settings(self, user_id: UserId) -> NotificationSettings: ...

    async def telegram_channel(self, user_id: UserId) -> ChannelView | None: ...


class NotificationRenderer(Protocol):
    """Текст уведомления по шаблонам gettext на языке читателя (ADR-0013)."""

    def renders(self, type_: NotificationType) -> bool:
        """Есть ли у типа шаблоны: без них уведомление не создаётся."""
        ...

    def text(
        self, type_: NotificationType, params: Mapping[str, str], locale: Locale
    ) -> RenderedText:
        """Заголовок и текст центра уведомлений — простой текст."""
        ...

    def telegram(
        self,
        type_: NotificationType,
        params: Mapping[str, str],
        link: str | None,
        locale: Locale,
    ) -> tuple[str, tuple[AppButton, ...]]:
        """HTML сообщения бота и кнопки web_app с кодом deep link."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class SendDeliveryPayload:
    delivery_id: UUID


GRANT_WRITE_ACCESS: Final = TaskRef("notifications.grant_write_access", BotStarted)
"""Подписчик BotStarted: /start разрешает боту писать — канал telegram доступен."""

SEND_DELIVERY: Final = TaskRef("notifications.send", SendDeliveryPayload, queue="notifications")
"""Отправить доставку в канал (не раньше `not_before`)."""

NOTIFY_ACCOUNT_RESTRICTED: Final = TaskRef(
    "notifications.notify_account_restricted", UserRestricted, queue="notifications"
)
NOTIFY_MODERATION_DECISION: Final = TaskRef(
    "notifications.notify_moderation_decision", ModerationDecisionMade, queue="notifications"
)
