"""Фикстуры notifications: use cases на сессии теста (откат в конце).

Внешнее — фейки (ADR-0020 §11): фасад identity отдаёт личный чат и язык, которые задал
тест; отправитель Telegram запоминает сообщения. Строка пользователя для FK на
identity.users вставляется SQL (tests/plugins/identity.py).
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.plugins.database import make_uow
from tests.plugins.identity import insert_user

from app.modules.notifications.application.ports import SEND_DELIVERY
from app.modules.notifications.application.queries import NotificationQueries
from app.modules.notifications.application.use_cases.block_telegram_channel import (
    BlockTelegramChannel,
)
from app.modules.notifications.application.use_cases.expire_stale_deliveries import (
    ExpireStaleDeliveries,
)
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
    GrantTelegramWriteAccessCommand,
)
from app.modules.notifications.application.use_cases.mark_notifications_read import (
    MarkNotificationsRead,
)
from app.modules.notifications.application.use_cases.notify import Notify
from app.modules.notifications.application.use_cases.send_delivery import SendDelivery
from app.modules.notifications.application.use_cases.update_notification_settings import (
    UpdateNotificationSettings,
)
from app.modules.notifications.domain.catalog import NotificationType
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.infrastructure.queries import SqlNotificationQuery
from app.modules.notifications.infrastructure.rendering import GettextNotificationRenderer
from app.modules.notifications.infrastructure.repositories import (
    SqlChannelRepository,
    SqlNotificationRepository,
    SqlSettingsRepository,
)
from app.modules.notifications.tests.fakes import FakeIdentity
from app.platform.contracts.events.notifications import GoodsWaitlistJoined, WriteAccessGranted
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.localized import Locale
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.queue.procrastinate_queue import ProcrastinateJobQueue
from app.platform.testing.clock import FakeClock
from app.platform.testing.queue import QueuedTask, queued_tasks
from app.platform.testing.telegram import RecordingTelegramSender

ON_WRITE_ACCESS = TaskRef("test.write_access_granted", WriteAccessGranted)
"""Подписка теста: WriteAccessGranted видно в procrastinate_jobs."""
ON_GOODS_WAITLIST = TaskRef("test.goods_waitlist_joined", GoodsWaitlistJoined)
"""Подписка теста: GoodsWaitlistJoined (S58, 7.5) видно в procrastinate_jobs."""

MINI_APP = "https://app.test/"


class AnyTypeRenderer(GettextNotificationRenderer):
    """Notify в тестах принимает любой тип каталога: группы, каналы и тихие часы у типов
    без шаблонов проверяются раньше, чем у них появятся тексты."""

    def renders(self, type_: NotificationType) -> bool:
        return True


@dataclass
class Notifications:
    session: AsyncSession
    clock: FakeClock
    identity: FakeIdentity
    sender: RecordingTelegramSender
    grant: GrantTelegramWriteAccess
    notify: Notify
    send: SendDelivery
    queries: NotificationQueries
    mark_read: MarkNotificationsRead
    update_settings: UpdateNotificationSettings
    block: BlockTelegramChannel
    expire: ExpireStaleDeliveries
    users: list[UserId] = field(default_factory=list)
    """Пользователи теста: задачи отправки — только их (API-тесты коммитят чужие)."""

    async def user_with_chat(self, locale: Locale = Locale.RU) -> tuple[UserId, int]:
        """Пользователь с личным чатом (chat_id = Telegram id) и языком интерфейса."""
        user_id = await insert_user(self.session)
        self.users.append(user_id)
        chat_id = 700_000_000 + new_id().int % 100_000_000
        self.identity.chats[user_id] = chat_id
        self.identity.locales[user_id] = locale
        return user_id, chat_id

    async def user_with_bot(self, locale: Locale = Locale.RU) -> UserId:
        """Пользователь, который разрешил боту писать (/start)."""
        user_id, _ = await self.user_with_chat(locale)
        await self.grant(GrantTelegramWriteAccessCommand(user_id=user_id, via=GrantedVia.BOT_START))
        return user_id

    async def channels(self, user_id: UserId) -> list[dict[str, object]]:
        return await self._rows(
            "SELECT kind, address, granted_via, granted_at, disabled_at"
            " FROM notifications.channels WHERE user_id = :user_id",
            user_id,
        )

    async def notifications(self, user_id: UserId) -> list[dict[str, object]]:
        return await self._rows(
            "SELECT id, type, payload, dedupe_key, priority, in_app, read_at"
            " FROM notifications.notifications WHERE user_id = :user_id ORDER BY id",
            user_id,
        )

    async def deliveries(self, user_id: UserId) -> list[dict[str, object]]:
        return await self._rows(
            "SELECT d.id, d.status, d.not_before, d.sent_at, d.provider_message_id, d.attempts,"
            " d.error"
            " FROM notifications.deliveries d JOIN notifications.notifications n"
            " ON n.id = d.notification_id WHERE n.user_id = :user_id ORDER BY d.id",
            user_id,
        )

    async def sends(self) -> list[QueuedTask]:
        """Поставленные задачи `notifications.send` доставок пользователей этого теста."""
        rows = await self.session.execute(
            text(
                "SELECT d.id::text FROM notifications.deliveries d"
                " JOIN notifications.notifications n ON n.id = d.notification_id"
                " WHERE n.user_id = ANY(:users)"
            ),
            {"users": self.users},
        )
        mine = {row[0] for row in rows}
        tasks = await queued_tasks(self.session, SEND_DELIVERY.name)
        return [t for t in tasks if t.payload.get("delivery_id") in mine]

    async def take_sends(self) -> None:
        """Воркер взял ждущие задачи отправки: они больше не держат queueing_lock."""
        await self.session.execute(
            text(
                "UPDATE procrastinate_jobs SET status = 'doing'"
                " WHERE task_name = :task AND status = 'todo'"
            ),
            {"task": SEND_DELIVERY.name},
        )
        await self.session.commit()

    async def announced(self, user_id: UserId) -> list[dict[str, object]]:
        """WriteAccessGranted пользователя, поставленные в очередь (payload события)."""
        tasks = await queued_tasks(self.session, ON_WRITE_ACCESS.name)
        return [t.payload for t in tasks if t.payload.get("user_id") == str(user_id)]

    async def waitlisted(self, user_id: UserId) -> list[dict[str, object]]:
        """GoodsWaitlistJoined пользователя, поставленные в очередь (payload события)."""
        tasks = await queued_tasks(self.session, ON_GOODS_WAITLIST.name)
        return [t.payload for t in tasks if t.payload.get("user_id") == str(user_id)]

    async def block_bot(self, user_id: UserId, at: datetime) -> None:
        """Пользователь заблокировал бота (403 — шаг 2.3b): канал выключен."""
        await self.session.execute(
            text("UPDATE notifications.channels SET disabled_at = :at WHERE user_id = :user_id"),
            {"at": at, "user_id": user_id},
        )
        await self.session.commit()  # чтения query-сервиса откатывают незафиксированное

    async def _rows(self, sql: str, user_id: UserId) -> list[dict[str, Any]]:
        rows = await self.session.execute(text(sql), {"user_id": user_id})
        return [dict(row._mapping) for row in rows]


@pytest.fixture
def notifications(db_session: AsyncSession, procrastinate_app: procrastinate.App) -> Notifications:
    clock = FakeClock()
    identity = FakeIdentity()
    sender = RecordingTelegramSender()
    events = EventRegistry()
    events.subscribe(WriteAccessGranted, ON_WRITE_ACCESS)
    events.subscribe(GoodsWaitlistJoined, ON_GOODS_WAITLIST)
    uow = make_uow(db_session, procrastinate_app, events)
    queue = ProcrastinateJobQueue(db_session, procrastinate_app)
    channels = SqlChannelRepository(db_session, uow)
    repository = SqlNotificationRepository(db_session, uow)
    settings = SqlSettingsRepository(db_session, uow)
    query = SqlNotificationQuery(db_session)
    translator = Translator.load()
    renderer = GettextNotificationRenderer(translator, MINI_APP)
    return Notifications(
        session=db_session,
        clock=clock,
        identity=identity,
        sender=sender,
        grant=GrantTelegramWriteAccess(uow, channels, identity, clock),
        notify=Notify(
            uow, repository, settings, channels, AnyTypeRenderer(translator, MINI_APP), queue, clock
        ),
        send=SendDelivery(
            uow, repository, channels, query, identity, renderer, sender, queue, clock
        ),
        queries=NotificationQueries(query, renderer),
        mark_read=MarkNotificationsRead(uow, repository, query, clock),
        update_settings=UpdateNotificationSettings(uow, settings, query, clock),
        block=BlockTelegramChannel(uow, channels),
        expire=ExpireStaleDeliveries(uow, repository, clock),
    )
