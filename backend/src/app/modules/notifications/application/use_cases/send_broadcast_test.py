"""Тестовая отправка рассылки себе (DEVELOPMENT_PLAN 2.7b): как увидит получатель.

Сотруднику — уведомление `broadcast` на выбранном языке тем же конвейером, что и рассылка
(рендер, лимитер, Bot API), но без проверки группы и тихих часов: проверку человек ждёт сейчас
(как `system.test`). Ключ — `broadcast-test:…`: в счётчики рассылки тест не входит, отмена его
не гасит. Боту нельзя писать сотруднику — TelegramNotLinkedError: сначала /start в боте.
"""

from dataclasses import dataclass
from types import MappingProxyType

from app.modules.notifications.application.dto import NewNotification
from app.modules.notifications.application.ports import (
    SEND_DELIVERY,
    BroadcastRepository,
    ChannelRepository,
    NotificationRepository,
    SendDeliveryPayload,
)
from app.modules.notifications.domain.broadcast import BroadcastId
from app.modules.notifications.domain.catalog import EventGroup, NotificationType, Priority
from app.modules.notifications.errors import TelegramNotLinkedError
from app.platform.audit.port import ActorKind, AuditEntry, AuditLog
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.localized import Locale
from app.platform.queue.port import JobQueue


@dataclass(frozen=True, slots=True, kw_only=True)
class SendBroadcastTestCommand:
    staff_id: UserId
    broadcast_id: BroadcastId
    locale: Locale


class SendBroadcastTest:
    def __init__(
        self,
        uow: UnitOfWork,
        broadcasts: BroadcastRepository,
        notifications: NotificationRepository,
        channels: ChannelRepository,
        queue: JobQueue,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._uow, self._broadcasts, self._notifications = uow, broadcasts, notifications
        self._channels, self._queue, self._audit, self._clock = channels, queue, audit, clock

    async def __call__(self, cmd: SendBroadcastTestCommand) -> None:
        now = self._clock.now()
        async with self._uow:
            broadcast = await self._broadcasts.get_for_update(cmd.broadcast_id)
            target = await self._channels.telegram_target(cmd.staff_id)
            if target is None or not target.writable:
                raise TelegramNotLinkedError()
            notification_id = await self._notifications.add(
                NewNotification(
                    user_id=cmd.staff_id,
                    type=NotificationType.BROADCAST,
                    dedupe_key=f"broadcast-test:{broadcast.id}:{new_id()}",
                    params=MappingProxyType(
                        {
                            "broadcast": str(broadcast.id),
                            # служебная группа не выключается: тест доходит при любых настройках
                            "group": EventGroup.ACCOUNT.value,
                            "locale": cmd.locale.value,
                        }
                    ),
                    link=None,
                    urgent=True,  # мимо тихих часов
                    priority=Priority.P0,
                    in_app=False,
                )
            )
            if notification_id is None:  # ключ с новым id не повторяется
                return
            delivery_id = await self._notifications.add_delivery(
                notification_id, target.channel_id, not_before=now
            )
            await self._queue.enqueue(
                SEND_DELIVERY,
                SendDeliveryPayload(delivery_id=delivery_id),
                dedup_key=str(delivery_id),
                priority=Priority.P0.job_priority,
            )
            await self._audit.record(
                AuditEntry(
                    action="notifications.broadcast.test_sent",
                    actor_kind=ActorKind.STAFF,
                    actor_id=cmd.staff_id,
                    entity_type="notifications.broadcast",
                    entity_id=broadcast.id,
                    changes={"locale": cmd.locale.value},
                )
            )
