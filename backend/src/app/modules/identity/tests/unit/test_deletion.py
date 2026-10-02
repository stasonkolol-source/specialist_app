"""Удаление аккаунта (DEVELOPMENT_PLAN 2.12a): запрос с grace-периодом, хэши способов входа и
обезличивание пользователя."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity.domain.deletion import (
    GRACE_PERIOD,
    DeletionRequest,
    DeletionSource,
    HashKind,
    identity_hash,
    login_hashes,
)
from app.modules.identity.domain.user import (
    DELETED_DISPLAY_NAME,
    AuthIdentity,
    AuthProvider,
    User,
    UserStatus,
)
from app.modules.identity.errors import AccountDeletedError
from app.platform.contracts.events.identity import UserDeleted
from app.platform.kernel.ids import CityId, UserId, new_id
from app.platform.kernel.localized import Locale

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
KEY = b"test-hash-key"


def test_request_waits_the_grace_period_unless_cancelled() -> None:
    request = DeletionRequest.request(UserId(new_id()), source=DeletionSource.TMA, now=NOW)

    assert request.execute_after == NOW + GRACE_PERIOD == NOW + timedelta(days=7)
    assert not request.due(NOW + GRACE_PERIOD - timedelta(seconds=1))
    assert request.due(NOW + GRACE_PERIOD)
    request.cancel(now=NOW + timedelta(days=1))
    assert not request.active
    assert not request.due(NOW + GRACE_PERIOD)


def test_completed_request_is_not_cancelled_later() -> None:
    request = DeletionRequest.request(UserId(new_id()), source=DeletionSource.BOT, now=NOW)
    request.complete(now=NOW + GRACE_PERIOD)
    request.cancel(now=NOW + GRACE_PERIOD + timedelta(hours=1))

    assert (request.completed_at, request.cancelled_at) == (NOW + GRACE_PERIOD, None)


def test_hashes_depend_on_the_key_and_the_kind() -> None:
    telegram = identity_hash(KEY, HashKind.TELEGRAM, "279058397")

    assert telegram == identity_hash(KEY, HashKind.TELEGRAM, "279058397")
    assert telegram != identity_hash(b"other-key", HashKind.TELEGRAM, "279058397")
    assert telegram != identity_hash(KEY, HashKind.PHONE, "279058397")
    assert login_hashes(KEY, telegram_ids=["279058397"], phone=None) == {
        telegram: HashKind.TELEGRAM
    }
    with_phone = login_hashes(KEY, telegram_ids=["279058397"], phone="+381601234567")
    assert sorted(with_phone.values()) == [HashKind.PHONE, HashKind.TELEGRAM]


def personal(user: User) -> tuple[str, list[AuthIdentity], str | None, CityId | None]:
    """Личные поля пользователя — функцией: mypy не сужает их по прошлым присваиваниям."""
    return user.display_name, user.identities, user.phone_e164, user.home_city_id


def test_forgotten_user_keeps_no_personal_data() -> None:
    user = User.register(
        provider=AuthProvider.TELEGRAM,
        subject="279058397",
        profile={"first_name": "Ana", "username": "ana_ns"},
        display_name="Ana Petrović",
        ui_locale=Locale.SR_LATN,
        now=NOW,
    )
    user.update_profile(now=NOW, home_city_id=CityId(1))
    user.phone_e164 = "+381601234567"
    user.pull_events()

    user.forget(now=NOW + GRACE_PERIOD)

    assert user.status is UserStatus.DELETED
    assert personal(user) == (DELETED_DISPLAY_NAME, [], None, None)
    assert [type(event) for event in user.pull_events()] == [UserDeleted]
    with pytest.raises(AccountDeletedError):
        user.ensure_active()
