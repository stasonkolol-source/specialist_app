"""Спайк 0.14: ротация refresh и детектор кражи на фейковом хранилище.

Алгоритм, который шаг 0.15a переносит в агрегат сессии identity (в БД — sessions):

- токен `<sid>.<secret>`; в сессии — хэш текущего секрета, хэш предыдущего и время ротации;
- совпал текущий → новый токен, текущий хэш становится предыдущим;
- совпал предыдущий в окне гонки (10 с) → 401 без отзыва: клиент повторил запрос, ответ
  на который потерялся, или два запроса обновились одновременно; Mini App обменяет initData;
- иначе (старый токен или подбор при известном sid) → отзыв всей сессии и sid в denylist;
- отозванная или истёкшая сессия → 401.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from app.platform.kernel.ids import new_id
from app.platform.security.errors import InvalidRefreshTokenError, SessionRevokedError
from app.platform.security.refresh import RefreshToken
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

RACE_WINDOW = timedelta(seconds=10)
TTL = timedelta(days=7)


@dataclass
class Session:
    id: str
    refresh_hash: bytes
    expires_at: datetime
    previous_hash: bytes | None = None
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None


class FakeSessions:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.rows: dict[str, Session] = {}
        self.denylist: set[str] = set()

    def start(self) -> RefreshToken:
        token = RefreshToken.new(new_id().hex)
        self.rows[token.session_id] = Session(
            id=token.session_id, refresh_hash=token.hash, expires_at=self.clock.now() + TTL
        )
        return token

    def refresh(self, raw: str) -> RefreshToken:
        presented = RefreshToken.parse(raw)
        session = self.rows.get(presented.session_id)
        now = self.clock.now()
        if session is None or now >= session.expires_at:
            raise InvalidRefreshTokenError
        if session.revoked_at is not None:
            raise SessionRevokedError
        if presented.matches(session.refresh_hash):
            fresh = RefreshToken.new(session.id)
            session.previous_hash, session.refresh_hash = session.refresh_hash, fresh.hash
            session.rotated_at = now
            session.expires_at = now + TTL
            return fresh
        in_race = session.rotated_at is not None and now - session.rotated_at <= RACE_WINDOW
        if in_race and presented.matches(session.previous_hash):
            raise InvalidRefreshTokenError
        session.revoked_at = now
        self.denylist.add(session.id)
        raise SessionRevokedError


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def sessions(clock: FakeClock) -> FakeSessions:
    return FakeSessions(clock)


def test_each_refresh_rotates_the_token(sessions: FakeSessions, clock: FakeClock) -> None:
    token = sessions.start()
    seen = {token.secret}
    for _ in range(5):
        clock.advance(timedelta(minutes=14))
        token = sessions.refresh(str(token))
        seen.add(token.secret)
    assert len(seen) == 6
    assert sessions.rows[token.session_id].revoked_at is None


def test_reuse_of_old_token_revokes_whole_chain(sessions: FakeSessions, clock: FakeClock) -> None:
    stolen = sessions.start()
    current = sessions.refresh(str(stolen))
    clock.advance(timedelta(minutes=1))

    with pytest.raises(SessionRevokedError):
        sessions.refresh(str(stolen))
    assert stolen.session_id in sessions.denylist
    with pytest.raises(SessionRevokedError):
        sessions.refresh(str(current))


def test_retry_in_race_window_does_not_revoke(sessions: FakeSessions, clock: FakeClock) -> None:
    first = sessions.start()
    second = sessions.refresh(str(first))
    clock.advance(timedelta(seconds=3))

    with pytest.raises(InvalidRefreshTokenError):
        sessions.refresh(str(first))
    assert sessions.rows[first.session_id].revoked_at is None
    sessions.refresh(str(second))


def test_guess_with_known_session_id_revokes(sessions: FakeSessions) -> None:
    token = sessions.start()
    with pytest.raises(SessionRevokedError):
        sessions.refresh(str(RefreshToken.new(token.session_id)))


def test_expired_and_unknown_sessions_are_rejected(
    sessions: FakeSessions, clock: FakeClock
) -> None:
    token = sessions.start()
    clock.advance(TTL)
    with pytest.raises(InvalidRefreshTokenError):
        sessions.refresh(str(token))
    with pytest.raises(InvalidRefreshTokenError):
        sessions.refresh(str(RefreshToken.new(new_id().hex)))
    assert sessions.rows[token.session_id].revoked_at is None
