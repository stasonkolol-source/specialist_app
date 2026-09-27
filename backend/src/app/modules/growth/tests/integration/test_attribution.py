"""Атрибуция первого касания на PostgreSQL: use case и подписчик UserRegistered (1.4b)."""

from datetime import UTC, datetime, timedelta

import procrastinate
import pytest
from pydantic import TypeAdapter
from tests.plugins.database import make_uow
from tests.plugins.identity import insert_user

from app.modules.growth.application.ports import RECORD_ATTRIBUTION
from app.modules.growth.application.use_cases.record_attribution import (
    RecordAttributionCommand,
)
from app.modules.growth.tasks import record_attribution
from app.modules.identity.api import UserNotFoundError
from app.platform.contracts.events.identity import EntryPoint, UserRegistered
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.tasks import TASKS
from app.platform.testing.queue import queued_tasks

from .conftest import Growth

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
SHARED_PROFILE = "s_02yBkPi1NksSnHWzckDH0V_rAB12CD"


def command(
    user_id: UserId,
    start_param: str | None,
    *,
    entry_point: EntryPoint = EntryPoint.MINI_APP,
    touched_at: datetime = NOW,
) -> RecordAttributionCommand:
    return RecordAttributionCommand(
        user_id=user_id, start_param=start_param, entry_point=entry_point, touched_at=touched_at
    )


async def test_first_touch_is_written_once(growth: Growth) -> None:
    user_id = await insert_user(growth.session)

    assert await growth.record(command(user_id, SHARED_PROFILE, entry_point=EntryPoint.BOT))
    later = NOW + timedelta(days=1)
    assert not await growth.record(command(user_id, "j_02y9UKmeRG6vSNbdsEYkkR", touched_at=later))

    assert await growth.attribution(user_id) == {
        "source": "specialist",
        "start_param": SHARED_PROFILE,
        "referral_code": "AB12CD",
        "entry_point": "bot",
        "first_seen_at": NOW,
    }


async def test_registration_without_code_is_organic(growth: Growth) -> None:
    user_id = await insert_user(growth.session)
    assert await growth.record(command(user_id, None))
    attribution = await growth.attribution(user_id)
    assert attribution is not None
    assert (attribution["source"], attribution["start_param"]) == ("organic", None)


async def test_unknown_user_is_not_found(growth: Growth) -> None:
    with pytest.raises(UserNotFoundError):
        await growth.record(command(UserId(new_id()), "h"))


# --- подписчик UserRegistered -------------------------------------------------------------


def test_growth_subscribes_to_user_registered() -> None:
    event = UserRegistered(user_id=UserId(new_id()), provider="telegram", occurred_at=NOW)
    assert RECORD_ATTRIBUTION in TASKS.event_registry().subscribers(event)


async def test_subscriber_records_event_from_queue(
    growth: Growth, procrastinate_app: procrastinate.App
) -> None:
    """Событие ставится в той же транзакции, payload переживает очередь, подписчик пишет."""
    user_id = await insert_user(growth.session)
    registry = EventRegistry()
    registry.subscribe(UserRegistered, RECORD_ATTRIBUTION)
    uow = make_uow(growth.session, procrastinate_app, registry)
    async with uow:
        uow.add_event(
            UserRegistered(
                user_id=user_id,
                provider="telegram",
                entry_point=EntryPoint.MINI_APP,
                start_param="h_rCHAN1",
                occurred_at=NOW,
            )
        )
    [task] = [
        t
        for t in await queued_tasks(growth.session, RECORD_ATTRIBUTION.name)
        if t.payload["user_id"] == str(user_id)
    ]
    event = TypeAdapter(UserRegistered).validate_python(task.payload)

    await record_attribution(event, growth.record)
    await record_attribution(event, growth.record)  # повтор задачи ничего не меняет

    attribution = await growth.attribution(user_id)
    assert attribution is not None
    assert (attribution["source"], attribution["referral_code"], attribution["entry_point"]) == (
        "home",
        "CHAN1",
        "mini_app",
    )


async def test_event_queued_before_this_step_is_organic(growth: Growth) -> None:
    """Payload без полей 1.4b (аддитивная схема): событие разбирается, касание — organic."""
    user_id = await insert_user(growth.session)
    legacy = {
        "user_id": str(user_id),
        "provider": "telegram",
        "occurred_at": NOW.isoformat(),
        "event_id": str(new_id()),
    }
    await record_attribution(TypeAdapter(UserRegistered).validate_python(legacy), growth.record)
    attribution = await growth.attribution(user_id)
    assert attribution is not None
    assert (attribution["source"], attribution["entry_point"]) == ("organic", None)
