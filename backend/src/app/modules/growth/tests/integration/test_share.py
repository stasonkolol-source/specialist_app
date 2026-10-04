"""«Поделиться» на PostgreSQL (DEVELOPMENT_PLAN 7.4): код приглашения создаётся один раз, ссылка
несёт его в `_r`, карточка — от Bot API (фейк), ShareCreated — в очереди; новый пользователь
по ссылке получает код в первом касании и событие AttributionRecorded; удаление аккаунта
стирает код."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import procrastinate
import pytest
from sqlalchemy import text
from tests.plugins.database import make_uow
from tests.plugins.identity import insert_user

from app.modules.growth.api import SharedLink, ShareTarget, ShareText
from app.modules.growth.application.use_cases.create_share import (
    BotLink,
    CreateShare,
    CreateShareCommand,
)
from app.modules.growth.application.use_cases.forget_attribution import (
    ForgetAttribution,
    ForgetAttributionCommand,
)
from app.modules.growth.application.use_cases.record_attribution import (
    RecordAttribution,
    RecordAttributionCommand,
)
from app.modules.growth.infrastructure.repositories import (
    SqlAttributionRepository,
    SqlReferralCodes,
)
from app.modules.identity.api import IdentityApi
from app.platform.analytics.tasks import CAPTURE_ATTRIBUTION_RECORDED, CAPTURE_SHARE_CREATED
from app.platform.contracts.events.growth import AttributionRecorded, ShareCreated
from app.platform.contracts.events.identity import EntryPoint
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.dispatcher import EventRegistry
from app.platform.testing.clock import FakeClock
from app.platform.testing.queue import queued_tasks
from app.platform.testing.telegram import RecordingPreparedMessages

from .conftest import Growth

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
TELEGRAM_ID = 777_000_111
CARD = ShareText(
    title="Алексей М.",
    description="Электрик",
    text="<b>Алексей М.</b> — специалист в «Соседях»",
    button_text="Открыть профиль",
)


@dataclass
class TelegramOf:
    """identity: Telegram id пользователя — только для адреса карточки."""

    telegram_id: int | None

    async def telegram_chat_id(self, user_id: UserId) -> int | None:
        return self.telegram_id


def sharing(
    growth: Growth,
    app: procrastinate.App,
    prepared: RecordingPreparedMessages,
    telegram_id: int | None = TELEGRAM_ID,
) -> CreateShare:
    registry = EventRegistry()
    registry.subscribe(ShareCreated, CAPTURE_SHARE_CREATED)
    uow = make_uow(growth.session, app, registry)
    return CreateShare(
        uow,
        SqlReferralCodes(growth.session, uow),
        cast(IdentityApi, TelegramOf(telegram_id)),
        prepared,
        FakeClock(NOW),
        BotLink(username="sosed_test_bot"),
    )


def request(
    sharer: UserId | None, target: ShareTarget = ShareTarget.SPECIALIST
) -> CreateShareCommand:
    return CreateShareCommand(sharer_id=sharer, target=target, target_id=new_id(), card=CARD)


def ref_of(link: SharedLink) -> str:
    return link.start_param.rsplit("_r", 1)[1]


async def test_sharer_link_carries_one_code_and_a_prepared_card(
    growth: Growth, procrastinate_app: procrastinate.App
) -> None:
    sharer = await insert_user(growth.session)
    prepared = RecordingPreparedMessages()
    share = sharing(growth, procrastinate_app, prepared)

    first = await share(request(sharer))
    second = await share(request(sharer, ShareTarget.JOB))

    assert first.start_param.startswith("s_")
    assert second.start_param.startswith("j_")
    assert ref_of(first) == ref_of(second)
    assert first.url == f"https://t.me/sosed_test_bot?startapp={first.start_param}"
    assert (first.prepared_message_id, second.prepared_message_id) == ("prepared-1", "prepared-2")
    [(telegram_id, card), _] = prepared.prepared
    assert (telegram_id, card.url, card.text) == (TELEGRAM_ID, first.url, CARD.text)
    events = [
        t.payload
        for t in await queued_tasks(growth.session, CAPTURE_SHARE_CREATED.name)
        if t.payload["sharer_id"] == str(sharer)
    ]
    assert [(e["entity_type"], e["prepared"]) for e in events] == [
        ("specialist", True),
        ("job", True),
    ]


async def test_without_card_the_client_shares_the_link(
    growth: Growth, procrastinate_app: procrastinate.App
) -> None:
    """Bot API не принял карточку или вошёл не через Telegram — ссылка без prepared id."""
    sharer = await insert_user(growth.session)
    failing = await sharing(growth, procrastinate_app, RecordingPreparedMessages(failing=True))(
        request(sharer)
    )
    no_telegram = await sharing(
        growth, procrastinate_app, RecordingPreparedMessages(), telegram_id=None
    )(request(sharer))

    assert (failing.prepared_message_id, no_telegram.prepared_message_id) == (None, None)
    assert ref_of(failing) == ref_of(no_telegram)


async def test_guest_gets_a_plain_link(
    growth: Growth, procrastinate_app: procrastinate.App
) -> None:
    prepared = RecordingPreparedMessages()
    link = await sharing(growth, procrastinate_app, prepared)(request(None, ShareTarget.JOB))

    assert link.start_param.startswith("j_")
    assert "_r" not in link.start_param[2:]
    assert link.prepared_message_id is None
    assert prepared.prepared == []


async def test_newcomer_by_shared_link_is_attributed_and_code_is_forgotten(
    growth: Growth, procrastinate_app: procrastinate.App
) -> None:
    sharer, newcomer = await insert_user(growth.session), await insert_user(growth.session)
    link = await sharing(growth, procrastinate_app, RecordingPreparedMessages())(request(sharer))
    registry = EventRegistry()
    registry.subscribe(AttributionRecorded, CAPTURE_ATTRIBUTION_RECORDED)
    uow = make_uow(growth.session, procrastinate_app, registry)
    attributions = SqlAttributionRepository(growth.session, uow)
    record = RecordAttribution(uow, attributions)

    assert await record(
        RecordAttributionCommand(
            user_id=newcomer,
            start_param=link.start_param,
            entry_point=EntryPoint.MINI_APP,
            touched_at=NOW,
        )
    )

    attribution = await growth.attribution(newcomer)
    assert attribution is not None
    assert (attribution["source"], attribution["referral_code"]) == ("specialist", ref_of(link))
    [event] = [
        t.payload
        for t in await queued_tasks(growth.session, CAPTURE_ATTRIBUTION_RECORDED.name)
        if t.payload["user_id"] == str(newcomer)
    ]
    assert (event["source"], event["has_referral"]) == ("specialist", True)

    await ForgetAttribution(uow, attributions, SqlReferralCodes(growth.session, uow))(
        ForgetAttributionCommand(user_id=sharer)
    )
    codes = await growth.session.execute(
        text("SELECT count(*) FROM growth.referral_codes WHERE owner_id = :id"), {"id": sharer}
    )
    assert codes.scalar_one() == 0
