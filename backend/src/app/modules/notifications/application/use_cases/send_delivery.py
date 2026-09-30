"""Отправить доставку в Telegram (задача `notifications.send`, ARCHITECTURE §11.2).

Чтения — до транзакции, отправка — внешний вызов, итог — своей короткой транзакцией:
- доставка уже не `queued` (повтор задачи) — ничего;
- задача пришла раньше `not_before` — ставится снова на `not_before`. Procrastinate
  отпускает задачу по часам базы, а сравниваем мы по часам воркера: расхождение до
  CLOCK_SLACK не гоняет задачу по кругу;
- боту писать нельзя (канал выключен) или получателя удалили — `suppressed`;
- настройки могли измениться, пока доставка ждала утра: группу выключили — `suppressed`,
  тихие часы сдвинули — доставка ждёт их нового конца (кроме срочного);
- текст — на языке получателя в момент отправки (язык мог смениться за ночь).

Сбой Bot API — повтор задачи; ответы 429, 403 и 400 разбирает адаптер шага 2.3b.
Доставка at-least-once: если воркер упадёт между отправкой и записью итога, сообщение
уйдёт ещё раз — Bot API ключа идемпотентности не знает.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.modules.identity.api import IdentityApi
from app.modules.notifications.application.ports import (
    SEND_DELIVERY,
    NotificationQuery,
    NotificationRenderer,
    NotificationRepository,
    SendDeliveryPayload,
)
from app.modules.notifications.domain.catalog import CATALOG, Channel
from app.modules.notifications.domain.notification import DeliveryId, DeliveryStatus
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.queue.port import JobQueue
from app.platform.telegram.port import OutgoingMessage, TelegramSender

CLOCK_SLACK = timedelta(seconds=30)
"""Настолько раньше срока можно отправить: полминуты до конца тихих часов — не ночь."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SendDeliveryCommand:
    delivery_id: DeliveryId


class SendDelivery:
    def __init__(
        self,
        uow: UnitOfWork,
        notifications: NotificationRepository,
        query: NotificationQuery,
        identity: IdentityApi,
        renderer: NotificationRenderer,
        sender: TelegramSender,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._notifications, self._query = uow, notifications, query
        self._identity, self._renderer, self._sender = identity, renderer, sender
        self._queue, self._clock = queue, clock

    async def __call__(self, cmd: SendDeliveryCommand) -> DeliveryStatus | None:
        """Итог доставки; None — отправлять нечего или ещё рано."""
        target = await self._query.delivery(cmd.delivery_id)
        if target is None or target.status is not DeliveryStatus.QUEUED:
            return None
        now = self._clock.now()
        if target.not_before - now > CLOCK_SLACK:  # задача пришла раньше срока: ждём его
            await self._postpone(target.id, target.not_before)
            return None
        user = await self._identity.get_user(target.user_id)
        if not target.writable or user is None or user.is_deleted:
            return await self._settle(target.id, DeliveryStatus.SUPPRESSED, now)
        spec = CATALOG[target.type]
        settings = await self._query.settings(target.user_id)
        if not settings.preferences.allows(spec.group, Channel.TELEGRAM):
            return await self._settle(target.id, DeliveryStatus.SUPPRESSED, now)
        if not (spec.quiet_exempt or target.urgent):
            release = settings.quiet_hours.release_at(now)
            if release - now > CLOCK_SLACK:
                await self._postpone(target.id, release)
                return None
        text, buttons = self._renderer.telegram(
            target.type, target.params, target.link, user.ui_locale
        )
        sent = await self._sender.send(
            OutgoingMessage(chat_id=target.chat_id, text=text, buttons=buttons)
        )
        return await self._settle(
            target.id,
            DeliveryStatus.SENT,
            self._clock.now(),
            provider_message_id=str(sent.message_id),
        )

    async def _postpone(self, delivery_id: DeliveryId, not_before: datetime) -> None:
        async with self._uow:
            if await self._notifications.postpone_delivery(delivery_id, not_before=not_before):
                await self._queue.enqueue(
                    SEND_DELIVERY,
                    SendDeliveryPayload(delivery_id=delivery_id),
                    dedup_key=str(delivery_id),
                    not_before=not_before,
                )

    async def _settle(
        self,
        delivery_id: DeliveryId,
        status: DeliveryStatus,
        now: datetime,
        *,
        provider_message_id: str | None = None,
    ) -> DeliveryStatus | None:
        async with self._uow:
            settled = await self._notifications.settle_delivery(
                delivery_id, status, now=now, provider_message_id=provider_message_id
            )
        return status if settled else None
