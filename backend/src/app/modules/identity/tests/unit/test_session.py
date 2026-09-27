"""Refresh-сессия: ротация, окно гонки, детектор кражи (DEVELOPMENT_PLAN 0.15a)."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity.domain.session import (
    RACE_WINDOW,
    RefreshOutcome,
    RevokeReason,
    Session,
)
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.principal import Platform
from app.platform.security.errors import InvalidRefreshTokenError, SessionRevokedError

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
TTL = timedelta(days=7)


def h(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def session() -> Session:
    return Session.open(
        user_id=UserId(new_id()),
        platform=Platform.TMA,
        bot_id=7000000001,
        amr=("tg_webapp",),
        refresh_hash=h("t0"),
        now=NOW,
        ttl=TTL,
    )


def test_open_sets_expiry_and_sid() -> None:
    s = session()
    assert s.expires_at == NOW + TTL
    assert s.sid == s.id.hex
    assert s.is_active(NOW)
    assert not s.is_active(NOW + TTL)


def test_rotation_moves_current_hash_to_previous_and_extends() -> None:
    s = session()
    later = NOW + timedelta(days=3)
    assert (
        s.refresh(presented_hash=h("t0"), new_hash=h("t1"), now=later, ttl=TTL)
        is RefreshOutcome.ROTATED
    )
    assert (s.refresh_hash, s.previous_refresh_hash) == (h("t1"), h("t0"))
    assert s.rotated_at == s.last_used_at == later
    assert s.expires_at == later + TTL


def test_previous_token_within_race_window_is_race() -> None:
    s = session()
    s.refresh(presented_hash=h("t0"), new_hash=h("t1"), now=NOW, ttl=TTL)
    outcome = s.refresh(presented_hash=h("t0"), new_hash=h("t2"), now=NOW + RACE_WINDOW, ttl=TTL)
    assert outcome is RefreshOutcome.RACE
    assert s.refresh_hash == h("t1")
    assert s.revoked_at is None


@pytest.mark.parametrize(
    ("presented", "delay"),
    [("t0", RACE_WINDOW + timedelta(seconds=1)), ("guess", timedelta(0)), ("t0", timedelta(0))],
    ids=["previous-too-late", "unknown-secret", "old-before-any-rotation"],
)
def test_reuse_revokes_session(presented: str, delay: timedelta) -> None:
    s = session()
    if presented == "t0" and delay:
        s.refresh(presented_hash=h("t0"), new_hash=h("t1"), now=NOW, ttl=TTL)
    elif presented == "t0":
        s.refresh(presented_hash=h("t0"), new_hash=h("t1"), now=NOW, ttl=TTL)
        s.refresh(presented_hash=h("t1"), new_hash=h("t2"), now=NOW, ttl=TTL)
    outcome = s.refresh(presented_hash=h(presented), new_hash=h("tx"), now=NOW + delay, ttl=TTL)
    assert outcome is RefreshOutcome.REUSED
    assert s.revoked_at == NOW + delay
    assert s.revoke_reason is RevokeReason.REFRESH_REUSED


def test_revoked_and_expired_sessions_refuse_without_changes() -> None:
    revoked = session()
    revoked.revoke(reason=RevokeReason.LOGOUT, now=NOW)
    with pytest.raises(SessionRevokedError):
        revoked.refresh(presented_hash=h("t0"), new_hash=h("t1"), now=NOW, ttl=TTL)

    expired = session()
    with pytest.raises(InvalidRefreshTokenError):
        expired.refresh(presented_hash=h("t0"), new_hash=h("t1"), now=NOW + TTL, ttl=TTL)
    assert expired.refresh_hash == h("t0")


def test_revoke_is_idempotent() -> None:
    s = session()
    s.revoke(reason=RevokeReason.LOGOUT, now=NOW)
    s.revoke(reason=RevokeReason.RESTRICTED, now=NOW + timedelta(hours=1))
    assert (s.revoked_at, s.revoke_reason) == (NOW, RevokeReason.LOGOUT)
