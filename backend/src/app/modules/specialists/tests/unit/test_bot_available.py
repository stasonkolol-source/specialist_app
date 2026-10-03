"""Кнопки /available: неизвестные данные не меняют доступность и не роняют обработчик."""

from datetime import UTC, datetime, time
from typing import Any, cast
from unittest.mock import AsyncMock, create_autospec

import pytest
from aiogram.types import CallbackQuery

from app.modules.specialists.application.use_cases.set_availability import (
    SetAvailabilityCommand,
)
from app.modules.specialists.bot.handlers import choose
from app.modules.specialists.domain.profile import Profile, ProfileKind
from app.platform.i18n.translator import Translator
from app.platform.kernel.ids import CityId, UserId, new_id
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", ["24", "99999999999999999999", "²", "", "no"])
async def test_invalid_callback_is_acknowledged_without_changing_availability(value: str) -> None:
    callback = create_autospec(CallbackQuery, instance=True)
    callback.data = f"avail:{value}"
    callback.answer = AsyncMock()
    set_availability = AsyncMock()

    await cast(Any, choose).__dishka_orig_func__(
        callback=callback,
        locale=Locale.RU,
        translator=create_autospec(Translator, instance=True),
        set_availability=set_availability,
        principal=Principal(user_id=UserId(new_id())),
    )

    callback.answer.assert_awaited_once_with()
    set_availability.assert_not_awaited()


@pytest.mark.parametrize("value", ["18", "20", "22", "off"])
async def test_valid_callback_changes_availability(value: str) -> None:
    callback = create_autospec(CallbackQuery, instance=True)
    callback.data = f"avail:{value}"
    callback.answer = AsyncMock()
    callback.message = None
    now = datetime(2026, 10, 1, 10, tzinfo=UTC)
    profile = Profile.create(
        user_id=UserId(new_id()),
        kind=ProfileKind.PRO,
        display_name="Ана",
        city_id=CityId(1),
        now=now,
    )
    until = None if value == "off" else time(int(value))
    profile.set_availability(until, now=now)
    set_availability = AsyncMock(return_value=profile)

    await cast(Any, choose).__dishka_orig_func__(
        callback=callback,
        locale=Locale.RU,
        translator=Translator.load(),
        set_availability=set_availability,
        principal=Principal(user_id=profile.user_id),
    )

    set_availability.assert_awaited_once_with(
        SetAvailabilityCommand(actor_id=profile.user_id, until=until)
    )
    callback.answer.assert_awaited_once_with()
