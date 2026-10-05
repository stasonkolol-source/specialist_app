"""Конвейер уведомлений на PostgreSQL (DEVELOPMENT_PLAN 2.3a, ARCHITECTURE §11.2).

«Готово, когда»: тихие часы переносят доставку; повтор события не создаёт дубль;
выключенная группа не создаёт доставку; рендер на трёх письменностях (unit-тест рендера
и отправка здесь).
"""

from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from app.modules.deals.api import DealsApi
from app.modules.jobs.api import JobsApi
from app.modules.notifications.application.dto import SettingsView
from app.modules.notifications.application.use_cases.mark_notifications_read import (
    MarkNotificationsReadCommand,
)
from app.modules.notifications.application.use_cases.notify import Notify, NotifyCommand
from app.modules.notifications.application.use_cases.send_delivery import SendDeliveryCommand
from app.modules.notifications.application.use_cases.update_notification_settings import (
    UpdateNotificationSettingsCommand,
)
from app.modules.notifications.domain.catalog import Channel, EventGroup, NotificationType
from app.modules.notifications.domain.notification import (
    DeliveryId,
    DeliveryStatus,
    NotificationId,
)
from app.modules.notifications.domain.settings import QuietHours
from app.modules.notifications.errors import MandatoryGroupError
from app.modules.notifications.infrastructure.rendering import GettextNotificationRenderer
from app.modules.notifications.tasks import (
    notify_account_restricted,
    notify_moderation_decision,
)
from app.modules.notifications.tests.integration.conftest import MINI_APP, Notifications
from app.platform.contracts.events.identity import RestrictionKind, UserRestricted
from app.platform.contracts.events.moderation import ModerationDecision, ModerationDecisionMade
from app.platform.i18n.translator import Translator
from app.platform.kernel.errors import ExternalServiceError
from app.platform.kernel.ids import CaseId, DealId, RestrictionId, UserId, new_id
from app.platform.kernel.localized import Locale
from app.platform.kernel.pagination import PageRequest
from app.platform.telegram.deeplinks import uuid_to_base62
from app.platform.telegram.port import AppButton

pytestmark = pytest.mark.integration

NIGHT = datetime(2026, 10, 12, 21, 30, tzinfo=UTC)
"""23:30 в Белграде (летнее время, UTC+2)."""
MORNING = datetime(2026, 10, 13, 6, 0, tzinfo=UTC)
"""08:00 в Белграде — конец тихих часов."""


def restricted(user_id: UserId, key: str = "r1", kind: str = "posting_blocked") -> NotifyCommand:
    return NotifyCommand(
        user_id=user_id,
        type=NotificationType.ACCOUNT_RESTRICTED,
        dedupe_key=f"account.restricted:{key}",
        params={"kind": kind},
        link="l_terms",
    )


def of_type(user_id: UserId, type_: NotificationType, key: str, **extra: object) -> NotifyCommand:
    return NotifyCommand(user_id=user_id, type=type_, dedupe_key=f"{type_}:{key}", **extra)  # type: ignore[arg-type]


def id_of(row: dict[str, object]) -> NotificationId:
    return NotificationId(cast(UUID, row["id"]))


async def delivery_of(notifications: Notifications) -> DeliveryId:
    [task] = await notifications.sends()
    return DeliveryId(UUID(str(task.payload["delivery_id"])))


async def test_notify_by_day_goes_to_the_bot_at_once(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()

    assert await notifications.notify(restricted(user_id)) is not None

    [row] = await notifications.notifications(user_id)
    assert (row["type"], row["in_app"], row["priority"]) == ("account.restricted", True, 0)
    assert row["payload"] == {
        "params": {"kind": "posting_blocked"},
        "link": "l_terms",
        "urgent": False,
    }
    [delivery] = await notifications.deliveries(user_id)
    assert (delivery["status"], delivery["not_before"]) == ("queued", notifications.clock.now())
    [task] = await notifications.sends()
    assert (task.queue, task.scheduled_at) == ("notifications", None)


async def test_notify_in_quiet_hours_waits_for_the_morning(notifications: Notifications) -> None:
    notifications.clock.set(NIGHT)
    user_id = await notifications.user_with_bot()

    await notifications.notify(restricted(user_id))

    [delivery] = await notifications.deliveries(user_id)
    assert delivery["not_before"] == MORNING
    [task] = await notifications.sends()
    assert task.scheduled_at == MORNING  # задача ждёт утра, а не просыпается ночью


async def test_notify_urgent_and_chat_messages_ignore_quiet_hours(
    notifications: Notifications,
) -> None:
    notifications.clock.set(NIGHT)
    user_id = await notifications.user_with_bot()

    await notifications.notify(of_type(user_id, NotificationType.MESSAGE_RECEIVED, "m1"))
    await notifications.notify(of_type(user_id, NotificationType.JOB_MATCHED, "j1", urgent=True))

    assert [d["not_before"] for d in await notifications.deliveries(user_id)] == [NIGHT, NIGHT]


async def test_notify_twice_for_one_event_creates_nothing_new(
    notifications: Notifications,
) -> None:
    user_id = await notifications.user_with_bot()

    first = await notifications.notify(restricted(user_id))
    again = await notifications.notify(restricted(user_id))

    assert first is not None
    assert again is None
    assert len(await notifications.notifications(user_id)) == 1
    assert len(await notifications.deliveries(user_id)) == 1
    assert len(await notifications.sends()) == 1


async def test_notify_skips_a_turned_off_group_but_not_service_messages(
    notifications: Notifications,
) -> None:
    user_id = await notifications.user_with_bot()
    await notifications.update_settings(
        UpdateNotificationSettingsCommand(
            user_id=user_id,
            choices={(EventGroup.RESPONSES, Channel.TELEGRAM): False},
            quiet_hours=QuietHours(),
            digest_hour=9,
        )
    )

    await notifications.notify(of_type(user_id, NotificationType.RESPONSE_RECEIVED, "x"))
    await notifications.notify(restricted(user_id))

    rows = await notifications.notifications(user_id)
    assert [(r["type"], r["in_app"]) for r in rows] == [
        ("response.received", True),  # в центре осталось, в бот — нет
        ("account.restricted", True),
    ]
    [delivery] = await notifications.deliveries(user_id)  # только служебное
    assert delivery["status"] == "queued"


async def test_notify_turned_off_in_app_hides_it_from_the_center(
    notifications: Notifications,
) -> None:
    user_id = await notifications.user_with_bot()
    await notifications.update_settings(
        UpdateNotificationSettingsCommand(
            user_id=user_id,
            choices={(EventGroup.RESPONSES, Channel.IN_APP): False},
            quiet_hours=QuietHours(),
            digest_hour=9,
        )
    )

    await notifications.notify(of_type(user_id, NotificationType.RESPONSE_RECEIVED, "x"))

    [row] = await notifications.notifications(user_id)
    assert row["in_app"] is False
    assert len(await notifications.deliveries(user_id)) == 1  # а бот пишет


async def test_notify_without_bot_permission_or_with_blocked_bot_keeps_the_center(
    notifications: Notifications,
) -> None:
    silent, _ = await notifications.user_with_chat()  # /start не было
    blocked = await notifications.user_with_bot()
    await notifications.block_bot(blocked, notifications.clock.now())

    await notifications.notify(restricted(silent, "a"))
    await notifications.notify(restricted(blocked, "b"))

    for user_id in (silent, blocked):
        assert [r["in_app"] for r in await notifications.notifications(user_id)] == [True]
        assert await notifications.deliveries(user_id) == []


async def test_notify_without_quiet_hours_delivers_at_night(notifications: Notifications) -> None:
    notifications.clock.set(NIGHT)
    user_id = await notifications.user_with_bot()
    await notifications.update_settings(
        UpdateNotificationSettingsCommand(
            user_id=user_id, choices={}, quiet_hours=QuietHours(enabled=False), digest_hour=9
        )
    )

    await notifications.notify(restricted(user_id))

    assert [d["not_before"] for d in await notifications.deliveries(user_id)] == [NIGHT]


async def test_notify_then_send_speaks_the_recipient_language(
    notifications: Notifications,
) -> None:
    user_id = await notifications.user_with_bot(Locale.SR_LATN)
    await notifications.notify(restricted(user_id))
    delivery_id = await delivery_of(notifications)

    status = await notifications.send(SendDeliveryCommand(delivery_id=delivery_id))

    assert status is DeliveryStatus.SENT
    [message] = notifications.sender.sent
    assert message.chat_id == notifications.identity.chats[user_id]
    assert message.text.startswith("<b>Nalog je ograničen</b>\nObjavljivanje zahteva")
    [button] = message.buttons
    assert isinstance(button, AppButton)
    assert (button.text, button.url) == ("Pravila platforme", f"{MINI_APP}?startapp=l_terms")
    [delivery] = await notifications.deliveries(user_id)
    assert (delivery["status"], delivery["provider_message_id"]) == ("sent", "1001")
    assert delivery["sent_at"] == notifications.clock.now()
    # повтор задачи: уже отправлено
    assert await notifications.send(SendDeliveryCommand(delivery_id=delivery_id)) is None
    assert len(notifications.sender.sent) == 1


async def test_send_that_came_before_the_morning_waits(notifications: Notifications) -> None:
    notifications.clock.set(NIGHT)
    user_id = await notifications.user_with_bot()
    await notifications.notify(restricted(user_id))
    delivery_id = await delivery_of(notifications)
    await notifications.take_sends()  # воркер взял задачу ночью: ставим новую, а не ту же

    assert await notifications.send(SendDeliveryCommand(delivery_id=delivery_id)) is None
    assert notifications.sender.sent == []
    [again] = await notifications.sends()
    assert again.scheduled_at == MORNING

    # часы воркера отстают от часов базы на секунды: отправка, а не новый круг
    notifications.clock.set(MORNING - timedelta(seconds=10))
    assert await notifications.send(SendDeliveryCommand(delivery_id=delivery_id)) == "sent"


async def test_send_follows_settings_changed_while_waiting(notifications: Notifications) -> None:
    notifications.clock.set(NIGHT)
    user_id = await notifications.user_with_bot()
    await notifications.notify(restricted(user_id, "a"))
    await notifications.notify(of_type(user_id, NotificationType.RESPONSE_RECEIVED, "x"))
    first, second = [
        DeliveryId(UUID(str(t.payload["delivery_id"]))) for t in await notifications.sends()
    ]
    await notifications.take_sends()
    # ночью человек выключил отклики в боте и продлил тихие часы до 09:00
    await notifications.update_settings(
        UpdateNotificationSettingsCommand(
            user_id=user_id,
            choices={(EventGroup.RESPONSES, Channel.TELEGRAM): False},
            quiet_hours=QuietHours(start=time(22, 0), end=time(9, 0)),
            digest_hour=9,
        )
    )
    notifications.clock.set(MORNING)

    assert await notifications.send(SendDeliveryCommand(delivery_id=first)) is None
    assert await notifications.send(SendDeliveryCommand(delivery_id=second)) == "suppressed"

    nine = MORNING + timedelta(hours=1)
    [postponed] = await notifications.sends()
    assert postponed.scheduled_at == nine
    restriction, _ = await notifications.deliveries(user_id)
    assert restriction["not_before"] == nine
    notifications.clock.set(nine)
    assert await notifications.send(SendDeliveryCommand(delivery_id=first)) == "sent"


async def test_urgent_notification_stays_urgent_until_sent(notifications: Notifications) -> None:
    notifications.clock.set(NIGHT)
    user_id = await notifications.user_with_bot()

    await notifications.notify(
        NotifyCommand(
            user_id=user_id,
            type=NotificationType.ACCOUNT_RESTRICTED,
            dedupe_key="account.restricted:urgent",
            params={"kind": "suspended"},
            urgent=True,
        )
    )

    [row] = await notifications.notifications(user_id)
    assert cast(dict[str, Any], row["payload"])["urgent"] is True
    delivery_id = await delivery_of(notifications)
    # и при отправке тихие часы его не держат
    assert await notifications.send(SendDeliveryCommand(delivery_id=delivery_id)) == "sent"


class WithoutMatchTemplates(GettextNotificationRenderer):
    """Рендерер, у которого нет шаблонов карточки B1: с 5.7 шаблоны есть у всех типов каталога,
    а проверка остаётся для следующего нового типа."""

    def renders(self, type_: NotificationType) -> bool:
        return type_ is not NotificationType.JOB_MATCHED and super().renders(type_)


async def test_notify_refuses_a_type_without_templates(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()
    production = Notify(
        notifications.notify._uow,
        notifications.notify._notifications,
        notifications.notify._settings,
        notifications.notify._channels,
        WithoutMatchTemplates(Translator.load(), MINI_APP),
        notifications.notify._queue,
        notifications.clock,
    )

    with pytest.raises(ValueError, match="no templates"):
        await production(of_type(user_id, NotificationType.JOB_MATCHED, "x"))

    assert await notifications.notifications(user_id) == []


async def test_send_is_suppressed_for_a_blocked_bot_or_a_deleted_user(
    notifications: Notifications,
) -> None:
    blocked = await notifications.user_with_bot()
    await notifications.notify(restricted(blocked, "a"))
    [first] = await notifications.sends()
    await notifications.block_bot(blocked, notifications.clock.now())

    status = await notifications.send(
        SendDeliveryCommand(delivery_id=DeliveryId(UUID(str(first.payload["delivery_id"]))))
    )

    assert status is DeliveryStatus.SUPPRESSED
    deleted = await notifications.user_with_bot()
    await notifications.notify(restricted(deleted, "b"))
    notifications.identity.deleted.add(deleted)
    [_, second] = await notifications.sends()
    status = await notifications.send(
        SendDeliveryCommand(delivery_id=DeliveryId(UUID(str(second.payload["delivery_id"]))))
    )
    assert status is DeliveryStatus.SUPPRESSED
    assert notifications.sender.sent == []


DAY = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
"""12:00 в Белграде."""


def expiring(user_id: UserId, key: str, valid_until: datetime) -> NotifyCommand:
    """«Заявка закроется через 2 ч»: после срока заявки сообщение — неправда."""
    return NotifyCommand(
        user_id=user_id,
        type=NotificationType.JOB_EXPIRING,
        dedupe_key=f"job.expiring:{key}",
        params={"job_id": str(new_id()), "title": "Люстра", "can_extend": "true"},
        valid_until=valid_until,
    )


async def test_notify_whose_deadline_falls_in_quiet_hours_skips_the_bot(
    notifications: Notifications,
) -> None:
    notifications.clock.set(NIGHT)
    user_id = await notifications.user_with_bot()

    created = await notifications.notify(expiring(user_id, "a", NIGHT + timedelta(hours=2)))

    assert created is not None
    assert await notifications.deliveries(user_id) == []  # утром «через 2 ч» было бы неправдой
    assert await notifications.sends() == []


async def test_send_after_the_deadline_is_suppressed_as_late(notifications: Notifications) -> None:
    notifications.clock.set(DAY)
    user_id = await notifications.user_with_bot()
    deadline = DAY + timedelta(hours=2)
    await notifications.notify(expiring(user_id, "b", deadline))
    [row] = await notifications.notifications(user_id)
    assert cast(dict[str, Any], row["payload"])["valid_until"] == deadline.isoformat()
    delivery_id = await delivery_of(notifications)

    notifications.clock.set(deadline)  # очередь задержала отправку до срока заявки
    status = await notifications.send(SendDeliveryCommand(delivery_id=delivery_id))

    assert status is DeliveryStatus.SUPPRESSED
    [delivery] = await notifications.deliveries(user_id)
    assert delivery["error"] == "late"
    assert notifications.sender.sent == []


async def test_send_that_would_wait_past_the_deadline_is_suppressed(
    notifications: Notifications,
) -> None:
    evening = datetime(2026, 10, 12, 19, 30, tzinfo=UTC)  # 21:30 в Белграде
    notifications.clock.set(evening)
    user_id = await notifications.user_with_bot()
    await notifications.notify(expiring(user_id, "c", evening + timedelta(hours=2)))
    delivery_id = await delivery_of(notifications)
    await notifications.take_sends()

    notifications.clock.set(NIGHT)  # воркер взял задачу уже в тихие часы
    status = await notifications.send(SendDeliveryCommand(delivery_id=delivery_id))

    assert status is DeliveryStatus.SUPPRESSED
    assert await notifications.sends() == []  # утра не ждём


async def test_send_failure_is_retried_later(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()
    await notifications.notify(restricted(user_id))
    notifications.sender.failing = True

    with pytest.raises(ExternalServiceError):
        await notifications.send(SendDeliveryCommand(delivery_id=await delivery_of(notifications)))

    [delivery] = await notifications.deliveries(user_id)
    assert delivery["status"] == "queued"  # повтор задачи отправит


async def test_center_lists_newest_first_in_the_reader_language(
    notifications: Notifications,
) -> None:
    user_id = await notifications.user_with_bot()
    for key, kind in (("a", "posting_blocked"), ("b", "responding_blocked"), ("c", "banned")):
        await notifications.notify(restricted(user_id, key, kind))
        notifications.clock.advance(timedelta(minutes=1))
    await notifications.notify(of_type(user_id, NotificationType.JOB_MATCHED, "bot-only"))

    first = await notifications.queries.feed(user_id, PageRequest(limit=2), Locale.SR_CYRL)

    assert [v.title for v in first.page.items] == ["Налог је блокиран", "Налог је ограничен"]
    assert first.unread == 3  # только центр: job.matched туда не ходит
    assert first.page.next_cursor is not None
    rest = await notifications.queries.feed(
        user_id, PageRequest(limit=2, cursor=first.page.next_cursor), Locale.RU
    )
    assert [v.body.split(".")[0] for v in rest.page.items] == [
        "Публиковать заявки и профиль пока нельзя"
    ]
    assert rest.page.next_cursor is None
    assert rest.page.items[0].link == "l_terms"


async def test_center_marks_only_own_notifications_read(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()
    other = await notifications.user_with_bot()
    await notifications.notify(restricted(user_id, "a"))
    await notifications.notify(restricted(user_id, "b"))
    await notifications.notify(restricted(other, "c"))
    [mine, _] = await notifications.notifications(user_id)
    [theirs] = await notifications.notifications(other)

    left = await notifications.mark_read(
        MarkNotificationsReadCommand(user_id=user_id, ids=[id_of(mine), id_of(theirs)])
    )

    assert left == 1
    assert [r["read_at"] is not None for r in await notifications.notifications(other)] == [False]
    assert (
        await notifications.mark_read(MarkNotificationsReadCommand(user_id=user_id, ids=None)) == 0
    )
    feed = await notifications.queries.feed(user_id, PageRequest(), Locale.RU)
    assert all(v.read for v in feed.page.items)


async def test_preferences_are_saved_as_changes_and_read_back(
    notifications: Notifications,
) -> None:
    user_id = await notifications.user_with_bot()

    view = await notifications.update_settings(
        UpdateNotificationSettingsCommand(
            user_id=user_id,
            choices={
                (EventGroup.JOB_MATCHES, Channel.TELEGRAM): False,
                (EventGroup.MARKETING, Channel.IN_APP): True,
                (EventGroup.MESSAGES, Channel.TELEGRAM): True,  # как по умолчанию
            },
            quiet_hours=QuietHours(enabled=False, start=time(23, 0), end=time(7, 0)),
            digest_hour=7,
        )
    )

    settings = (await notifications.queries.settings(user_id)).settings
    assert settings == view.settings
    assert settings.preferences.allows(EventGroup.JOB_MATCHES, Channel.TELEGRAM) is False
    assert settings.preferences.allows(EventGroup.MARKETING, Channel.IN_APP) is True
    assert settings.preferences.allows(EventGroup.MARKETING, Channel.TELEGRAM) is False
    assert (settings.quiet_hours.enabled, settings.digest_hour) == (False, 7)
    assert view.telegram is not None
    assert view.telegram.writable
    rows = await notifications._rows(
        "SELECT event_group, channel, enabled FROM notifications.preferences"
        " WHERE user_id = :user_id ORDER BY event_group",
        user_id,
    )
    assert rows == [
        {"event_group": "job_matches", "channel": "telegram", "enabled": False},
        {"event_group": "marketing", "channel": "in_app", "enabled": True},
    ]

    await notifications.update_settings(
        UpdateNotificationSettingsCommand(
            user_id=user_id, choices={}, quiet_hours=QuietHours(), digest_hour=9
        )
    )
    reset = (await notifications.queries.settings(user_id)).settings
    assert reset.preferences.allows(EventGroup.JOB_MATCHES, Channel.TELEGRAM) is True


async def test_preferences_cannot_turn_off_service_notifications(
    notifications: Notifications,
) -> None:
    user_id = await notifications.user_with_bot()

    with pytest.raises(MandatoryGroupError):
        await notifications.update_settings(
            UpdateNotificationSettingsCommand(
                user_id=user_id,
                choices={(EventGroup.ACCOUNT, Channel.TELEGRAM): False},
                quiet_hours=QuietHours(),
                digest_hour=9,
            )
        )


def goods_launch(
    *, on: bool, channels: tuple[Channel, ...] = tuple(Channel)
) -> dict[tuple[EventGroup, Channel], bool]:
    return {(EventGroup.GOODS_LAUNCH, channel): on for channel in channels}


async def save_choices(
    notifications: Notifications,
    user_id: UserId,
    choices: dict[tuple[EventGroup, Channel], bool],
) -> SettingsView:
    return await notifications.update_settings(
        UpdateNotificationSettingsCommand(
            user_id=user_id, choices=choices, quiet_hours=QuietHours(), digest_hour=9
        )
    )


async def test_goods_launch_opt_in_joins_the_waitlist_once(notifications: Notifications) -> None:
    """S58 «Сообщить о запуске» (7.5): включение группы — одно событие для аналитики, повтор и
    сохранение S43 без изменений — ни одного; после отписки новое включение — снова событие."""
    user_id = await notifications.user_with_bot()

    view = await save_choices(notifications, user_id, goods_launch(on=True))
    await save_choices(
        notifications, user_id, goods_launch(on=True) | {(EventGroup.DEALS, Channel.IN_APP): False}
    )

    assert view.settings.preferences.allows(EventGroup.GOODS_LAUNCH, Channel.TELEGRAM)
    joined = await notifications.waitlisted(user_id)
    assert [(e["user_id"], e["bot_writable"]) for e in joined] == [(str(user_id), True)]

    await save_choices(notifications, user_id, goods_launch(on=False))  # переключатель S43
    settings = (await notifications.queries.settings(user_id)).settings
    assert not settings.preferences.allows(EventGroup.GOODS_LAUNCH, Channel.IN_APP)
    await save_choices(notifications, user_id, goods_launch(on=True, channels=(Channel.IN_APP,)))

    assert len(await notifications.waitlisted(user_id)) == 2


async def test_goods_waitlist_says_whether_the_bot_can_write(
    notifications: Notifications,
) -> None:
    user_id, _chat_id = await notifications.user_with_chat()  # боту писать ещё нельзя

    await save_choices(notifications, user_id, goods_launch(on=True))

    assert [e["bot_writable"] for e in await notifications.waitlisted(user_id)] == [False]


async def test_notify_on_restriction_except_a_shadow_ban(notifications: Notifications) -> None:
    user_id = await notifications.user_with_bot()
    restriction_id = RestrictionId(new_id())
    until = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
    event = UserRestricted(
        user_id=user_id,
        restriction_id=restriction_id,
        kind=RestrictionKind.POSTING_BLOCKED,
        reason_code="spam",
        until=until,
        case_id=None,
        occurred_at=notifications.clock.now(),
    )

    await notify_account_restricted(event, notifications.notify)
    await notify_account_restricted(event, notifications.notify)  # повтор задачи
    shadow = UserRestricted(
        user_id=user_id,
        restriction_id=RestrictionId(new_id()),
        kind=RestrictionKind.SHADOW_BANNED,
        reason_code="spam",
        until=None,
        case_id=None,
        occurred_at=notifications.clock.now(),
    )
    await notify_account_restricted(shadow, notifications.notify)

    [row] = await notifications.notifications(user_id)
    assert row["dedupe_key"] == f"account.restricted:{restriction_id}"
    assert row["payload"] == {
        "params": {"kind": "posting_blocked", "until": until.isoformat()},
        "link": "l_terms",
        "urgent": False,
    }


class ResponseJobs:
    """Фасад jobs для уведомления о решении по отклику: только заявка отклика."""

    def __init__(self, links: dict[UUID, UUID]) -> None:
        self._links = links

    async def response_job(self, response_id: UUID) -> UUID | None:
        return self._links.get(response_id)


class DisputeDeals:
    """Фасад deals для решения по спору: только сделка спора."""

    def __init__(self, deals: dict[UUID, DealId]) -> None:
        self._deals = deals

    async def dispute(self, dispute_id: UUID) -> SimpleNamespace | None:
        deal_id = self._deals.get(dispute_id)
        return SimpleNamespace(deal_id=deal_id) if deal_id is not None else None


async def test_notify_author_about_a_rejection_only(notifications: Notifications) -> None:
    """«Исправить» ведёт туда, где объект правят (UX-аудит №11), а не на Главную."""
    user_id = await notifications.user_with_bot()
    job_id = new_id()
    response_id, response_job = new_id(), new_id()
    dispute_id, dispute_deal = new_id(), DealId(new_id())
    jobs = cast(JobsApi, ResponseJobs({response_id: response_job}))
    deals = cast(DealsApi, DisputeDeals({dispute_id: dispute_deal}))

    def decided(
        decision: ModerationDecision, entity: str, entity_id: UUID
    ) -> ModerationDecisionMade:
        return ModerationDecisionMade(
            case_id=CaseId(new_id()),
            author_id=user_id,
            entity_type=entity,
            entity_id=entity_id,
            decision=decision,
            decision_code="contact_leak",
            occurred_at=notifications.clock.now(),
        )

    for decision, entity, entity_id in (
        (ModerationDecision.REJECTED, "job", job_id),
        (ModerationDecision.REJECTED, "review", new_id()),
        (ModerationDecision.APPROVED, "job", new_id()),
        (ModerationDecision.REJECTED, "response", response_id),
        (ModerationDecision.REJECTED, "profile", new_id()),
        (ModerationDecision.REJECTED, "portfolio", new_id()),
        (ModerationDecision.REJECTED, "review_reply", new_id()),
        (ModerationDecision.REJECTED, "dispute", dispute_id),
        (ModerationDecision.REJECTED, "message", new_id()),
    ):
        await notify_moderation_decision(
            decided(decision, entity, entity_id), notifications.notify, jobs, deals
        )

    rows = await notifications.notifications(user_id)
    payloads = [cast(dict[str, Any], r["payload"]) for r in rows]
    assert [(p["params"]["entity_type"], p["link"]) for p in payloads] == [
        ("job", f"j_{uuid_to_base62(job_id)}"),  # «Исправить» ведёт к заявке
        ("review", "m_reviews"),  # «Мои отзывы» S28
        ("response", f"j_{uuid_to_base62(response_job)}"),  # отклик — к его заявке
        ("profile", "m_profile"),  # кабинет S33: черновик не публичен, `s_` — «недоступен»
        ("portfolio", "m_portfolio"),  # портфолио S37
        ("review_reply", "m_reviews"),
        ("dispute", f"p_{uuid_to_base62(dispute_deal)}"),  # спор S52
        ("message", "h"),  # своего экрана по id сообщения нет — на Главную
    ]
