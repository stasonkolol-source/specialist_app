"""Уведомить пользователя (ARCHITECTURE §11.2, DEVELOPMENT_PLAN 2.3a).

Одна точка для всех типов: подписчики событий (tasks.py) переводят событие в команду. В
одной транзакции:
- уведомление с `dedupe_key` — повтор события ничего не создаёт;
- в центре уведомлений (S42) оно видно, если канал `in_app` у группы включён;
- доставка в личный чат с ботом — если тип ходит в бот, группа там включена и боту можно
  писать; не раньше конца тихих часов (кроме срочного), и задача `notifications.send`
  ставится на то же время.

Выключенная группа доставки не создаёт; служебную (решения модерации, санкции) не
выключить. Текст не хранится: его собирают на языке читателя при показе и отправке.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.modules.notifications.application.dto import NewNotification
from app.modules.notifications.application.ports import (
    SEND_DELIVERY,
    ChannelRepository,
    NotificationRenderer,
    NotificationRepository,
    SendDeliveryPayload,
    SettingsRepository,
)
from app.modules.notifications.domain.catalog import CATALOG, Channel, NotificationType
from app.modules.notifications.domain.notification import NotificationId
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.ids import UserId
from app.platform.queue.port import JobQueue
from app.platform.telegram.deeplinks import parse_start_param


@dataclass(frozen=True, slots=True, kw_only=True)
class NotifyCommand:
    user_id: UserId
    type: NotificationType
    dedupe_key: str
    """Идемпотентность: `<тип>:<id источника>` (например, `account.restricted:<санкция>`)."""
    params: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """Машинные значения для шаблона (коды, id, даты ISO) — не готовый текст."""
    link: str | None = None
    """Код deep link (§11.4): куда ведут кнопка бота и строка центра уведомлений."""
    urgent: bool = False
    """Срочное (заявка `asap`): уходит и в тихие часы."""


class Notify:
    def __init__(
        self,
        uow: UnitOfWork,
        notifications: NotificationRepository,
        settings: SettingsRepository,
        channels: ChannelRepository,
        renderer: NotificationRenderer,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._notifications, self._settings = uow, notifications, settings
        self._channels, self._renderer = channels, renderer
        self._queue, self._clock = queue, clock

    async def __call__(self, cmd: NotifyCommand) -> NotificationId | None:
        """id уведомления; None — такое уже было (повтор события)."""
        if not self._renderer.renders(cmd.type):
            # ошибка программиста: строка без шаблонов сломала бы центр уведомлений читателя
            raise ValueError(f"notification type {cmd.type} has no templates")
        if cmd.link is not None and parse_start_param(cmd.link) is None:
            raise DomainValidationError(field="link", value=cmd.link)
        spec = CATALOG[cmd.type]
        now = self._clock.now()
        async with self._uow:
            settings = await self._settings.load(cmd.user_id)
            allows = settings.preferences.allows
            notification_id = await self._notifications.add(
                NewNotification(
                    user_id=cmd.user_id,
                    type=cmd.type,
                    dedupe_key=cmd.dedupe_key,
                    params=cmd.params,
                    link=cmd.link,
                    urgent=cmd.urgent,
                    priority=spec.priority,
                    in_app=Channel.IN_APP in spec.channels and allows(spec.group, Channel.IN_APP),
                )
            )
            if notification_id is None:
                return None
            if Channel.TELEGRAM not in spec.channels or not allows(spec.group, Channel.TELEGRAM):
                return notification_id
            target = await self._channels.telegram_target(cmd.user_id)
            if target is None or not target.writable:  # писать не разрешали или бот заблокирован
                return notification_id
            release = (
                now if spec.quiet_exempt or cmd.urgent else settings.quiet_hours.release_at(now)
            )
            delivery_id = await self._notifications.add_delivery(
                notification_id, target.channel_id, not_before=release
            )
            await self._queue.enqueue(
                SEND_DELIVERY,
                SendDeliveryPayload(delivery_id=delivery_id),
                dedup_key=str(delivery_id),
                not_before=release if release > now else None,
                priority=spec.priority.job_priority,
            )
        return notification_id
