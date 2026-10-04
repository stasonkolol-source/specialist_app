"""Карточки заявки по подписке после её закрытия (DEVELOPMENT_PLAN 5.7, ARCHITECTURE §11.3).

«После закрытия заявки кнопки становятся неактивными»: отправленной карточке B1 ставится
`notifications.retire_card`, и правка оставляет «Открыть заявку» и неактивную «Приём откликов
закрыт»; карточка, ждавшая конца тихих часов, не уходит. Час подборки — из настроек уведомлений.
"""

from datetime import UTC, datetime, time
from uuid import UUID

import procrastinate
import pytest
from tests.plugins.database import make_uow

from app.modules.notifications.application.use_cases.notify import NotifyCommand
from app.modules.notifications.application.use_cases.retire_card import (
    RetireCard,
    RetireCardCommand,
)
from app.modules.notifications.application.use_cases.retire_job_cards import (
    RetireJobCards,
    RetireJobCardsCommand,
)
from app.modules.notifications.application.use_cases.send_delivery import SendDeliveryCommand
from app.modules.notifications.application.use_cases.update_notification_settings import (
    UpdateNotificationSettingsCommand,
)
from app.modules.notifications.domain.catalog import NotificationType
from app.modules.notifications.domain.notification import DeliveryId
from app.modules.notifications.domain.settings import QuietHours
from app.modules.notifications.infrastructure.digest_schedule import SettingsDigestSchedule
from app.modules.notifications.infrastructure.queries import SqlNotificationQuery
from app.modules.notifications.infrastructure.rendering import GettextNotificationRenderer
from app.modules.notifications.infrastructure.repositories import SqlNotificationRepository
from app.modules.notifications.tests.integration.conftest import MINI_APP, Notifications
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.procrastinate_queue import ProcrastinateJobQueue
from app.platform.telegram.port import AppButton, InactiveButton, TelegramRejectedError
from app.platform.testing.queue import queued_tasks

pytestmark = pytest.mark.integration

LINK = "j_0Bd1u4lEy5iE5j9cQ0ZJqh"


def card(user_id: UserId, job_id: UUID) -> NotifyCommand:
    return NotifyCommand(
        user_id=user_id,
        type=NotificationType.JOB_MATCHED,
        dedupe_key=f"job.matched:{job_id}:{user_id}",
        params={"job_id": str(job_id), "alert_id": str(new_id()), "title": "Повесить люстру"},
        link=LINK,
    )


def retire_use_cases(
    notifications: Notifications, procrastinate_app: procrastinate.App
) -> tuple[RetireJobCards, RetireCard]:
    session = notifications.session
    uow = make_uow(session, procrastinate_app)
    query = SqlNotificationQuery(session)
    retire = RetireJobCards(
        uow,
        SqlNotificationRepository(session, uow),
        query,
        ProcrastinateJobQueue(session, procrastinate_app),
        notifications.clock,
    )
    renderer = GettextNotificationRenderer(Translator.load(), MINI_APP, notifications.clock)
    one = RetireCard(query, notifications.identity, renderer, notifications.sender)
    return retire, one


async def test_closed_job_cards_lose_their_buttons(
    notifications: Notifications, procrastinate_app: procrastinate.App
) -> None:
    job_id = new_id()
    ana = await notifications.user_with_bot()
    night = await notifications.user_with_bot()
    await notifications.notify(card(ana, job_id))
    [task] = await notifications.sends()
    await notifications.take_sends()
    await notifications.send(
        SendDeliveryCommand(delivery_id=DeliveryId(UUID(task.payload["delivery_id"])))
    )
    notifications.clock.set(datetime(2026, 10, 5, 21, 30, tzinfo=UTC))  # 23:30 по Белграду
    await notifications.notify(card(night, job_id))  # ждёт конца тихих часов
    retire, one = retire_use_cases(notifications, procrastinate_app)

    retired = await retire(RetireJobCardsCommand(job_id=job_id))

    assert retired == 1
    [waiting] = await notifications.deliveries(night)
    assert (waiting["status"], waiting["error"]) == ("suppressed", "job_closed")
    [sent] = await notifications.deliveries(ana)
    tasks = await queued_tasks(notifications.session, "notifications.retire_card")
    assert str(sent["id"]) in {t.payload["delivery_id"] for t in tasks}

    assert await one(RetireCardCommand(delivery_id=DeliveryId(UUID(str(sent["id"])))))
    [edited] = notifications.sender.edited
    assert edited.message_id == int(str(sent["provider_message_id"]))
    open_job, closed = edited.buttons
    assert isinstance(open_job, AppButton)
    assert open_job.url == f"{MINI_APP}?startapp={LINK}"
    assert closed == InactiveButton(text="Приём откликов закрыт")


async def test_deleted_message_is_not_an_error(
    notifications: Notifications, procrastinate_app: procrastinate.App
) -> None:
    job_id = new_id()
    ana = await notifications.user_with_bot()
    await notifications.notify(card(ana, job_id))
    [task] = await notifications.sends()
    await notifications.take_sends()
    await notifications.send(
        SendDeliveryCommand(delivery_id=DeliveryId(UUID(task.payload["delivery_id"])))
    )
    [sent] = await notifications.deliveries(ana)
    _, one = retire_use_cases(notifications, procrastinate_app)
    notifications.sender.error = TelegramRejectedError("message to edit not found")

    assert await one(RetireCardCommand(delivery_id=DeliveryId(UUID(str(sent["id"]))))) is False


async def test_digest_hour_comes_from_notification_settings(notifications: Notifications) -> None:
    early, default = await notifications.user_with_bot(), await notifications.user_with_bot()
    await notifications.update_settings(
        UpdateNotificationSettingsCommand(
            user_id=early,
            choices={},
            quiet_hours=QuietHours(start=time(23, 0), end=time(6, 0)),
            digest_hour=7,
        )
    )
    schedule = SettingsDigestSchedule(SqlNotificationQuery(notifications.session))

    at_seven = await schedule.due([early, default], datetime(2026, 10, 5, 5, 0, tzinfo=UTC))
    at_nine = await schedule.due([early, default], datetime(2026, 10, 5, 7, 0, tzinfo=UTC))

    assert at_seven == frozenset({early})  # 07:00 по Белграду
    assert at_nine == frozenset({default})  # 09:00 — по умолчанию
