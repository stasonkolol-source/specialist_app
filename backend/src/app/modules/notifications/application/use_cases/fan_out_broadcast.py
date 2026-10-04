"""Разбор аудитории рассылки пачками (задача `notifications.fan_out_broadcast`, 2.7b).

Одна пачка — одна транзакция под блокировкой строки рассылки (отмена ждёт её конца или
случается до неё — тогда пачка ничего не ставит):
- кандидаты — по возрастанию id после курсора: канал telegram доступен и группа рассылки
  включена в боте (opt-in — только явным выбором человека, S43);
- сегмент и город — фасадами identity и specialists, удалённые аккаунты отсеиваются;
- каждому — уведомление `broadcast` с ключом `broadcast:<рассылка>:<получатель>` (повтор задачи
  второго не создаёт) и доставка не раньше конца его тихих часов, как у любого несрочного
  уведомления; задача отправки — с приоритетом P4, ниже всех остальных;
- полная пачка ставит следующую, неполная — проверку завершения (`finish_broadcast`).

Отправка — общий конвейер (`notifications.send`): лимитер Valkey 25 msg/s на бота и 1 msg/s на
чат, 429 и 403, повторная проверка настроек и тихих часов перед отправкой.
"""

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final

from app.modules.notifications.application.dto import NewNotification
from app.modules.notifications.application.ports import (
    FAN_OUT_BROADCAST,
    FINISH_BROADCAST,
    SEND_DELIVERY,
    AudienceSource,
    BroadcastPayload,
    BroadcastRepository,
    ChannelRepository,
    NotificationRepository,
    SendDeliveryPayload,
    SettingsRepository,
)
from app.modules.notifications.domain.broadcast import Broadcast, BroadcastId, dedupe_prefix
from app.modules.notifications.domain.catalog import CATALOG, Channel, NotificationType
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId
from app.platform.queue.port import JobQueue

BATCH: Final = 200
"""Получателей за транзакцию: отмена ждёт не дольше одной пачки."""
SPEC: Final = CATALOG[NotificationType.BROADCAST]


@dataclass(frozen=True, slots=True, kw_only=True)
class FanOutBroadcastCommand:
    broadcast_id: BroadcastId


class FanOutBroadcast:
    def __init__(
        self,
        uow: UnitOfWork,
        broadcasts: BroadcastRepository,
        audience: AudienceSource,
        notifications: NotificationRepository,
        settings: SettingsRepository,
        channels: ChannelRepository,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._broadcasts, self._audience = uow, broadcasts, audience
        self._notifications, self._settings, self._channels = notifications, settings, channels
        self._queue, self._clock = queue, clock

    async def __call__(self, cmd: FanOutBroadcastCommand) -> int:
        """Сколько доставок поставлено этой пачкой."""
        now = self._clock.now()
        queued = 0
        async with self._uow:
            broadcast = await self._broadcasts.get_for_update(cmd.broadcast_id)
            if not broadcast.begin():  # отменили, пока задача ждала
                return 0
            candidates = await self._audience.candidates(
                broadcast.group, after=broadcast.cursor, limit=BATCH
            )
            segments = await self._audience.segments(candidates)
            for user_id in candidates:
                segment = segments.get(user_id)
                if segment is not None and broadcast.targeting.includes(segment):
                    queued += await self._deliver(broadcast, user_id, now)
            if candidates:
                broadcast.advance(candidates[-1])
            await self._broadcasts.save(broadcast)
            payload = BroadcastPayload(broadcast_id=broadcast.id)
            if len(candidates) == BATCH:
                await self._queue.enqueue(
                    FAN_OUT_BROADCAST,
                    payload,
                    dedup_key=f"{broadcast.id}:{broadcast.cursor}",
                    priority=SPEC.priority.job_priority,
                )
            else:
                await self._queue.enqueue(
                    FINISH_BROADCAST,
                    payload,
                    dedup_key=str(broadcast.id),
                    priority=SPEC.priority.job_priority,
                )
        return queued

    async def _deliver(self, broadcast: Broadcast, user_id: UserId, now: datetime) -> int:
        notification_id = await self._notifications.add(
            NewNotification(
                user_id=user_id,
                type=NotificationType.BROADCAST,
                dedupe_key=f"{dedupe_prefix(broadcast.id)}{user_id}",
                params=MappingProxyType(
                    {"broadcast": str(broadcast.id), "group": broadcast.group.value}
                ),
                link=None,
                urgent=False,
                priority=SPEC.priority,
                in_app=False,
            )
        )
        if notification_id is None:  # повтор пачки: этому получателю уже поставлено
            return 0
        settings = await self._settings.load(user_id)
        if not settings.preferences.allows(broadcast.group, Channel.TELEGRAM):
            return 0  # выключил группу между отбором и записью: уведомление без доставки
        target = await self._channels.telegram_target(user_id)
        if target is None or not target.writable:
            return 0
        release = settings.quiet_hours.release_at(now)
        delivery_id = await self._notifications.add_delivery(
            notification_id, target.channel_id, not_before=release
        )
        await self._queue.enqueue(
            SEND_DELIVERY,
            SendDeliveryPayload(delivery_id=delivery_id),
            dedup_key=str(delivery_id),
            not_before=release if release > now else None,
            priority=SPEC.priority.job_priority,
        )
        return 1
