"""Рассылки из админки на настоящей базе (DEVELOPMENT_PLAN 2.7b).

Разбор аудитории ставит каждому получателю доставку и задачу `notifications.send` — тот же
конвейер с лимитером Valkey, что у остальных уведомлений, — с приоритетом ниже задач-подписчиков;
выключенная группа и заблокированный бот — не получатели, тихие часы откладывают доставку,
отмена гасит ждущие, каждое действие сотрудника — в audit_log.
"""

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from tests.plugins.database import make_uow

from app.modules.notifications.application.ports import FAN_OUT_BROADCAST, FINISH_BROADCAST
from app.modules.notifications.application.use_cases.cancel_broadcast import (
    CancelBroadcast,
    CancelBroadcastCommand,
)
from app.modules.notifications.application.use_cases.create_broadcast import (
    CreateBroadcast,
    CreateBroadcastCommand,
)
from app.modules.notifications.application.use_cases.fan_out_broadcast import (
    FanOutBroadcast,
    FanOutBroadcastCommand,
)
from app.modules.notifications.application.use_cases.finish_broadcast import (
    FinishBroadcast,
    FinishBroadcastCommand,
)
from app.modules.notifications.application.use_cases.send_delivery import SendDeliveryCommand
from app.modules.notifications.application.use_cases.start_broadcast import (
    StartBroadcast,
    StartBroadcastCommand,
)
from app.modules.notifications.application.use_cases.update_notification_settings import (
    UpdateNotificationSettingsCommand,
)
from app.modules.notifications.domain.broadcast import Audience, BroadcastId, BroadcastStatus
from app.modules.notifications.domain.catalog import Channel, EventGroup, Priority
from app.modules.notifications.domain.notification import DeliveryId, DeliveryStatus
from app.modules.notifications.domain.settings import QuietHours
from app.modules.notifications.infrastructure.broadcasts import (
    FacadeAudienceSource,
    SqlBroadcastQuery,
    SqlBroadcastRepository,
)
from app.modules.notifications.infrastructure.repositories import (
    SqlChannelRepository,
    SqlNotificationRepository,
    SqlSettingsRepository,
)
from app.modules.notifications.tests.integration.conftest import Notifications
from app.modules.specialists.api import ProfileRef
from app.platform.audit.sql import SqlAuditLog
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.procrastinate_queue import ProcrastinateJobQueue
from app.platform.testing.queue import queued_tasks

pytestmark = pytest.mark.integration

DAY = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)  # 12:00 в Белграде
NIGHT = datetime(2026, 10, 5, 21, 30, tzinfo=UTC)  # 23:30 в Белграде — тихие часы


@dataclass
class StubSpecialists:
    """SpecialistsApi.profiles_of: профили исполнителей задаёт тест."""

    profiles: dict[UserId, ProfileRef] = field(default_factory=dict)

    async def profiles_of(self, user_ids: Collection[UserId]) -> dict[UserId, ProfileRef]:
        return {u: p for u, p in self.profiles.items() if u in set(user_ids)}


class OwnAudience(FacadeAudienceSource):
    """Настоящий запрос кандидатов, но только пользователи теста: API-тесты коммитят своих."""

    def __init__(self, notifications: Notifications, specialists: StubSpecialists) -> None:
        super().__init__(notifications.session, notifications.identity, specialists)  # type: ignore[arg-type]
        self._mine = notifications.users

    async def candidates(
        self, group: EventGroup, *, after: UserId | None, limit: int
    ) -> list[UserId]:
        found = await super().candidates(group, after=after, limit=limit)
        return [user_id for user_id in found if user_id in self._mine]


@dataclass
class Broadcasts:
    notifications: Notifications
    specialists: StubSpecialists
    create: CreateBroadcast
    start: StartBroadcast
    cancel: CancelBroadcast
    fan_out: FanOutBroadcast
    finish: FinishBroadcast
    query: SqlBroadcastQuery

    async def subscriber(self, *, news: bool = True) -> UserId:
        """Пользователь с ботом и включёнными «Новостями «Соседей»» (opt-in S43)."""
        user_id = await self.notifications.user_with_bot()
        await self.notifications.update_settings(
            UpdateNotificationSettingsCommand(
                user_id=user_id,
                choices={(EventGroup.MARKETING, Channel.TELEGRAM): news},
                quiet_hours=QuietHours(),
                digest_hour=9,
            )
        )
        return user_id

    async def draft(self, staff: UserId, audience: Audience = Audience.ALL) -> BroadcastId:
        return await self.create(
            CreateBroadcastCommand(
                staff_id=staff,
                text={"ru": "Привет, соседи!", "sr-Latn": "Zdravo, susedi!"},
                audience=audience,
                link="m_profile",
            )
        )

    async def audit(self, staff: UserId) -> list[str]:
        rows = await self.notifications.session.execute(
            text(
                "SELECT action FROM platform.audit_log WHERE actor_id = :staff"
                " AND entity_type = 'notifications.broadcast' ORDER BY id"
            ),
            {"staff": staff},
        )
        return [row[0] for row in rows]


@pytest.fixture
def broadcasts(notifications: Notifications, procrastinate_app: object) -> Broadcasts:
    session, clock = notifications.session, notifications.clock
    uow = make_uow(session, procrastinate_app)  # type: ignore[arg-type]
    queue = ProcrastinateJobQueue(session, procrastinate_app)  # type: ignore[arg-type]
    repository = SqlBroadcastRepository(session, uow)
    deliveries = SqlNotificationRepository(session, uow)
    audit = SqlAuditLog(session, uow)
    query = SqlBroadcastQuery(session, clock)
    specialists = StubSpecialists()
    return Broadcasts(
        notifications=notifications,
        specialists=specialists,
        create=CreateBroadcast(uow, repository, audit, clock),
        start=StartBroadcast(uow, repository, queue, audit, clock),
        cancel=CancelBroadcast(uow, repository, deliveries, audit, clock),
        fan_out=FanOutBroadcast(
            uow,
            repository,
            OwnAudience(notifications, specialists),
            deliveries,
            SqlSettingsRepository(session, uow),
            SqlChannelRepository(session, uow),
            queue,
            clock,
        ),
        finish=FinishBroadcast(uow, repository, query, queue, clock),
        query=query,
    )


async def _send_all(notifications: Notifications) -> None:
    for task in await notifications.sends():
        delivery_id = DeliveryId(task.payload["delivery_id"])
        await notifications.send(SendDeliveryCommand(delivery_id=delivery_id))


async def test_fan_out_goes_through_the_send_queue_below_everything(
    broadcasts: Broadcasts,
) -> None:
    notifications = broadcasts.notifications
    notifications.clock.set(DAY)
    staff = await notifications.user_with_bot()
    reader = await broadcasts.subscriber()
    await broadcasts.subscriber(news=False)  # новости выключены — не получатель
    blocked = await broadcasts.subscriber()
    await notifications.block_bot(blocked, DAY)  # бот заблокирован — не получатель

    broadcast_id = await broadcasts.draft(staff)
    assert await broadcasts.start(StartBroadcastCommand(staff_id=staff, broadcast_id=broadcast_id))
    fan_out = await queued_tasks(notifications.session, FAN_OUT_BROADCAST.name)
    assert [t.priority for t in fan_out if t.payload["broadcast_id"] == str(broadcast_id)] == [
        Priority.P4.job_priority
    ]

    assert await broadcasts.fan_out(FanOutBroadcastCommand(broadcast_id=broadcast_id)) == 1
    again = await broadcasts.fan_out(FanOutBroadcastCommand(broadcast_id=broadcast_id))
    assert again == 0  # повтор задачи второго сообщения не ставит

    sends = await notifications.sends()
    assert [t.priority for t in sends] == [-1]  # ниже задач-подписчиков (0)
    await _send_all(notifications)
    [message] = notifications.sender.sent
    assert "Привет, соседи!" in message.text
    stats = await broadcasts.query.stats(broadcast_id)
    assert (stats.recipients, stats.sent, stats.queued) == (1, 1, 0)
    assert [d["status"] for d in await notifications.deliveries(reader)] == ["sent"]

    finished = await broadcasts.finish(FinishBroadcastCommand(broadcast_id=broadcast_id))
    assert finished is BroadcastStatus.DONE
    assert await broadcasts.audit(staff) == [
        "notifications.broadcast.created",
        "notifications.broadcast.started",
    ]


async def test_quiet_hours_defer_and_opt_out_skips(broadcasts: Broadcasts) -> None:
    notifications = broadcasts.notifications
    notifications.clock.set(NIGHT)
    staff = await notifications.user_with_bot()
    sleeper = await broadcasts.subscriber()
    changed_mind = await broadcasts.subscriber()
    broadcast_id = await broadcasts.draft(staff)
    await broadcasts.start(StartBroadcastCommand(staff_id=staff, broadcast_id=broadcast_id))
    await broadcasts.fan_out(FanOutBroadcastCommand(broadcast_id=broadcast_id))

    stats = await broadcasts.query.stats(broadcast_id)
    assert (stats.recipients, stats.queued, stats.deferred) == (2, 2, 2)  # ждут 08:00
    assert {t.scheduled_at for t in await notifications.sends()} == {
        datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
    }
    finished = await broadcasts.finish(FinishBroadcastCommand(broadcast_id=broadcast_id))
    assert finished is BroadcastStatus.SENDING  # пока есть ждущие — идёт
    assert await queued_tasks(notifications.session, FINISH_BROADCAST.name)

    await broadcasts.notifications.update_settings(  # к утру выключил новости
        UpdateNotificationSettingsCommand(
            user_id=changed_mind,
            choices={(EventGroup.MARKETING, Channel.TELEGRAM): False},
            quiet_hours=QuietHours(),
            digest_hour=9,
        )
    )
    notifications.clock.set(datetime(2026, 10, 6, 6, 0, tzinfo=UTC))
    await _send_all(notifications)
    assert len(notifications.sender.sent) == 1
    assert [d["status"] for d in await notifications.deliveries(sleeper)] == ["sent"]
    stats = await broadcasts.query.stats(broadcast_id)
    assert (stats.sent, stats.skipped, stats.queued) == (1, 1, 0)


async def test_cancel_stops_pending_sends_and_is_audited(broadcasts: Broadcasts) -> None:
    notifications = broadcasts.notifications
    notifications.clock.set(NIGHT)
    staff = await notifications.user_with_bot()
    reader = await broadcasts.subscriber()
    specialist = await broadcasts.subscriber()
    broadcasts.specialists.profiles[specialist] = ProfileRef(
        id=new_id(), kind="pro", status="published", is_founding=True
    )
    broadcast_id = await broadcasts.draft(staff, audience=Audience.FOUNDING)
    await broadcasts.start(StartBroadcastCommand(staff_id=staff, broadcast_id=broadcast_id))
    await broadcasts.fan_out(FanOutBroadcastCommand(broadcast_id=broadcast_id))
    assert await notifications.deliveries(reader) == []  # не Founding — не получатель

    assert (
        await broadcasts.cancel(CancelBroadcastCommand(staff_id=staff, broadcast_id=broadcast_id))
        == 1
    )
    notifications.clock.set(datetime(2026, 10, 6, 6, 0, tzinfo=UTC))
    await _send_all(notifications)
    assert notifications.sender.sent == []
    [delivery] = await notifications.deliveries(specialist)
    assert (delivery["status"], delivery["error"]) == (DeliveryStatus.SUPPRESSED, "cancelled")
    assert await broadcasts.fan_out(FanOutBroadcastCommand(broadcast_id=broadcast_id)) == 0
    assert await broadcasts.audit(staff) == [
        "notifications.broadcast.created",
        "notifications.broadcast.started",
        "notifications.broadcast.cancelled",
    ]
