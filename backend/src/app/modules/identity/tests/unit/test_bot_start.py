"""Отложенный /start сохраняет время разрешения писать, а не время обработки апдейта."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.filters import CommandObject
from aiogram.types import Chat, Message, User

from app.modules.identity.application.config import IdentityConfig
from app.modules.identity.application.dto import TelegramProfile
from app.modules.identity.application.ports import DeletedIdentities, IdentityQuery, UserRepository
from app.modules.identity.application.use_cases.register_telegram_user import (
    RegisterTelegramUser,
    RegisterTelegramUserCommand,
)
from app.modules.identity.bot.handlers import start
from app.platform.contracts.events.identity import BotStarted
from app.platform.db.port import UnitOfWork
from app.platform.i18n.translator import Translator
from app.platform.settings import TelegramSettings
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

STARTED = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


def registration(now: datetime) -> tuple[RegisterTelegramUser, MagicMock, AsyncMock]:
    uow = MagicMock(spec=UnitOfWork)
    users = AsyncMock(spec=UserRepository)
    users.find_by_identity.return_value = None
    deleted = AsyncMock(spec=DeletedIdentities)
    deleted.find.return_value = None
    register = RegisterTelegramUser(
        uow=uow,
        users=users,
        query=AsyncMock(spec=IdentityQuery),
        deleted=deleted,
        config=IdentityConfig(
            bot_id=123,
            refresh_ttl_tma=timedelta(days=7),
            refresh_ttl_mobile=timedelta(days=30),
            hash_key=b"test-key",
        ),
        clock=FakeClock(now),
    )
    return register, uow, users


@pytest.mark.parametrize("delay", [timedelta(0), timedelta(minutes=5)])
async def test_start_event_keeps_telegram_message_date(
    delay: timedelta, monkeypatch: pytest.MonkeyPatch
) -> None:
    processed = STARTED + delay
    register, uow, users = registration(processed)
    message = Message(
        message_id=1,
        date=STARTED,
        chat=Chat(id=456, type="private"),
        from_user=User(id=456, is_bot=False, first_name="Ana"),
        text="/start",
    )
    monkeypatch.setattr(Message, "answer", AsyncMock())

    dependencies = {
        RegisterTelegramUser: register,
        Translator: Translator.load(),
        TelegramSettings: MagicMock(spec=TelegramSettings, mini_app_url=None),
    }
    container = AsyncMock()
    container.get.side_effect = lambda dependency, component: dependencies[dependency]
    data: dict[str, Any] = {
        "message": message,
        "command": CommandObject(command="start"),
        "dishka_container": container,
    }

    await start(**data)

    event = uow.add_event.call_args.args[0]
    assert isinstance(event, BotStarted)
    assert event.occurred_at == STARTED
    user = users.add.call_args.args[0]
    assert user.created_at == processed
    assert event.user_id == user.id


async def test_registration_without_message_date_uses_current_time() -> None:
    register, uow, _ = registration(STARTED)

    await register(RegisterTelegramUserCommand(profile=TelegramProfile(id=456, first_name="Ana")))

    event = uow.add_event.call_args.args[0]
    assert isinstance(event, BotStarted)
    assert event.occurred_at == STARTED
