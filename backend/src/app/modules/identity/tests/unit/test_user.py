"""Агрегат пользователя (DEVELOPMENT_PLAN 0.15a)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity.domain.user import (
    FALLBACK_DISPLAY_NAME,
    MAX_DISPLAY_NAME,
    AuthProvider,
    User,
    UserStatus,
    clean_display_name,
    locale_from_language,
)
from app.modules.identity.errors import (
    AccountDeletedError,
    InvalidDisplayNameError,
    UserAlreadyDeletedError,
)
from app.platform.contracts.events.identity import UserRegistered, UserUpdated
from app.platform.kernel.errors import ProgrammingError
from app.platform.kernel.localized import Locale

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def register(**overrides: object) -> User:
    values: dict[str, object] = {
        "provider": AuthProvider.TELEGRAM,
        "subject": "279058397",
        "profile": {"first_name": "Ana", "username": "ana_ns"},
        "display_name": "Ana Petrović",
        "ui_locale": Locale.SR_LATN,
        "now": NOW,
    }
    return User.register(**(values | overrides))  # type: ignore[arg-type]


def test_register_creates_active_user_with_identity_and_event() -> None:
    user = register()
    assert user.status is UserStatus.ACTIVE
    assert user.trust_level == 0
    assert user.version == 1
    assert user.timezone == "Europe/Belgrade"
    [identity] = user.identities
    assert (identity.provider, identity.subject) == (AuthProvider.TELEGRAM, "279058397")
    assert identity.last_login_at == NOW
    [event] = user.pull_events()
    assert isinstance(event, UserRegistered)
    assert event.user_id == user.id
    assert event.provider == "telegram"


def test_login_refreshes_profile_snapshot() -> None:
    user = register()
    later = NOW + timedelta(days=2)
    user.record_login(
        provider=AuthProvider.TELEGRAM,
        subject="279058397",
        profile={"first_name": "Anna"},
        now=later,
    )
    assert user.identities[0].profile == {"first_name": "Anna"}
    assert user.identities[0].last_login_at == later
    assert user.last_seen_at == later


def test_login_with_unknown_identity_is_a_bug() -> None:
    with pytest.raises(ProgrammingError):
        register().record_login(provider=AuthProvider.APPLE, subject="x", profile={}, now=NOW)


def test_deleted_account_cannot_log_in_or_be_deleted_twice() -> None:
    user = register()
    user.delete(by=user.id, now=NOW, reason="user_request")
    assert user.status is UserStatus.DELETED
    assert user.deleted_at == NOW
    [change] = user.pull_history()
    assert (change.from_, change.to, change.reason) == (
        UserStatus.ACTIVE,
        UserStatus.DELETED,
        "user_request",
    )
    with pytest.raises(AccountDeletedError):
        user.record_login(provider=AuthProvider.TELEGRAM, subject="279058397", profile={}, now=NOW)
    with pytest.raises(UserAlreadyDeletedError):
        user.delete(by=None, now=NOW)


@pytest.mark.parametrize(
    ("language", "locale"),
    [
        (None, Locale.RU),
        ("", Locale.RU),
        ("ru", Locale.RU),
        ("uk", Locale.RU),
        ("kk", Locale.RU),
        ("sr", Locale.SR_LATN),
        ("sr-Cyrl", Locale.SR_LATN),
        ("hr", Locale.SR_LATN),
        ("en", Locale.EN),
        ("en-GB", Locale.EN),
        ("de", Locale.RU),
    ],
)
def test_locale_from_telegram_language(language: str | None, locale: Locale) -> None:
    assert locale_from_language(language) is locale


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("Ana", "Petrović"), "Ana Petrović"),
        (("  Ana  ", None), "Ana"),
        (("An\u200ba", "\u202ePet\u0007"), "Ana Pet"),
        (("", None), FALLBACK_DISPLAY_NAME),
        (("\u200b",), FALLBACK_DISPLAY_NAME),
        (("Ян" * 50,), ("Ян" * 50)[:MAX_DISPLAY_NAME]),
    ],
)
def test_display_name_is_cleaned(parts: tuple[str | None, ...], expected: str) -> None:
    assert clean_display_name(*parts) == expected


def test_update_profile_changes_name_and_locale_with_event() -> None:
    user = register()
    user.pull_events()
    user.update_profile(display_name="  Ana   P. ", ui_locale=Locale.SR_CYRL, now=NOW)
    assert (user.display_name, user.ui_locale) == ("Ana P.", Locale.SR_CYRL)
    [event] = user.pull_events()
    assert isinstance(event, UserUpdated)
    user.update_profile(display_name="Ana P.", ui_locale=None, now=NOW)
    assert user.pull_events() == []


def test_update_profile_rejects_invisible_name_and_deleted_user() -> None:
    user = register()
    with pytest.raises(InvalidDisplayNameError):
        user.update_profile(display_name="\u200b ", ui_locale=None, now=NOW)
    user.delete(by=None, now=NOW)
    with pytest.raises(AccountDeletedError):
        user.update_profile(display_name="Ana", ui_locale=None, now=NOW)
