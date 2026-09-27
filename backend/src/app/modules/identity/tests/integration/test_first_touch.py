"""Первое касание и /start для growth и notifications (DEVELOPMENT_PLAN 1.4b).

identity ниже growth и notifications по DAG: он только публикует события —
`UserRegistered` с кодом deep link и `BotStarted` на каждый /start, — а адрес личного
чата отдаёт фасадом.
"""

import procrastinate
import pytest
from tests.plugins.database import make_uow

from app.modules.identity.application.use_cases.authenticate_telegram import (
    AuthenticateTelegram,
    AuthenticateTelegramCommand,
)
from app.modules.identity.application.use_cases.register_telegram_user import (
    RegisterTelegramUser,
    RegisterTelegramUserCommand,
)
from app.modules.identity.infrastructure.repositories import (
    SqlSessionRepository,
    SqlUserRepository,
)
from app.platform.contracts.events.identity import BotStarted, UserRegistered
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.testing.queue import queued_tasks

from .conftest import CONFIG, Identity, telegram_profile

pytestmark = pytest.mark.integration

ON_REGISTERED = TaskRef("test.first_touch_registered", UserRegistered)
ON_BOT_STARTED = TaskRef("test.first_touch_bot_started", BotStarted)
LINK = "s_02yBkPi1NksSnHWzckDH0V_rAB12CD"


class Harness:
    """Use cases входа с подписками теста: события видны в procrastinate_jobs."""

    def __init__(self, identity: Identity, app: procrastinate.App) -> None:
        registry = EventRegistry()
        registry.subscribe(UserRegistered, ON_REGISTERED)
        registry.subscribe(BotStarted, ON_BOT_STARTED)
        uow = make_uow(identity.session, app, registry)
        users = SqlUserRepository(identity.session, uow)
        self.identity = identity
        self.authenticate = AuthenticateTelegram(
            uow,
            users,
            SqlSessionRepository(identity.session, uow),
            identity.query,
            identity.tokens,
            CONFIG,
            identity.clock,
        )
        self.register = RegisterTelegramUser(uow, users, identity.query, identity.clock)

    async def payloads(self, task: TaskRef[object], user_id: UserId) -> list[dict[str, object]]:
        tasks = await queued_tasks(self.identity.session, task.name)
        return [t.payload for t in tasks if t.payload.get("user_id") == str(user_id)]


@pytest.fixture
def harness(identity: Identity, procrastinate_app: procrastinate.App) -> Harness:
    return Harness(identity, procrastinate_app)


async def test_mini_app_registration_carries_startapp(harness: Harness) -> None:
    profile = telegram_profile()
    first = await harness.authenticate(
        AuthenticateTelegramCommand(profile=profile, start_param=LINK)
    )
    again = await harness.authenticate(
        AuthenticateTelegramCommand(profile=profile, start_param="h_rOTHER")
    )

    assert not again.is_new
    [event] = await harness.payloads(ON_REGISTERED, first.tokens.user_id)
    assert (event["entry_point"], event["start_param"]) == ("mini_app", LINK)
    assert await harness.payloads(ON_BOT_STARTED, first.tokens.user_id) == []


async def test_bot_start_registers_with_payload_and_announces_every_start(
    harness: Harness,
) -> None:
    profile = telegram_profile()
    user, is_new = await harness.register(
        RegisterTelegramUserCommand(profile=profile, start_param=LINK)
    )
    _, again = await harness.register(RegisterTelegramUserCommand(profile=profile))

    assert is_new
    assert not again
    [event] = await harness.payloads(ON_REGISTERED, user.id)
    assert (event["entry_point"], event["start_param"]) == ("bot", LINK)
    assert len(await harness.payloads(ON_BOT_STARTED, user.id)) == 2


@pytest.mark.parametrize("payload", ["my phone is 381601234567", "h" * 65, "привет"])
async def test_typed_text_after_start_is_not_stored(harness: Harness, payload: str) -> None:
    user, _ = await harness.register(
        RegisterTelegramUserCommand(profile=telegram_profile(), start_param=payload)
    )
    [event] = await harness.payloads(ON_REGISTERED, user.id)
    assert event["start_param"] is None


async def test_facade_gives_private_chat_of_active_user(identity: Identity) -> None:
    profile = telegram_profile()
    result = await identity.authenticate(AuthenticateTelegramCommand(profile=profile))
    user_id = result.tokens.user_id

    assert await identity.facade.telegram_chat_id(user_id) == profile.id
    assert await identity.facade.telegram_chat_id(UserId(new_id())) is None

    async with identity.uow:
        user = await identity.users.get(user_id)
        user.delete(by=user.id, now=identity.clock.now())
        await identity.users.save(user)
    assert await identity.facade.telegram_chat_id(user_id) is None
