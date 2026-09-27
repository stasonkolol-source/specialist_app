"""Refresh-токен: 256 бит, хранится только SHA-256 (DEVELOPMENT_PLAN 0.14, ADR-0009)."""

import base64
import hashlib

import pytest

from app.platform.kernel.ids import new_id
from app.platform.security.errors import InvalidRefreshTokenError
from app.platform.security.refresh import RefreshToken

pytestmark = pytest.mark.unit


def test_refresh_token_has_256_bits_and_session_prefix() -> None:
    sid = new_id().hex
    token = RefreshToken.new(sid)
    assert len(base64.urlsafe_b64decode(token.secret + "=")) == 32
    assert str(token).startswith(f"{sid}.")
    assert RefreshToken.new(sid).secret != token.secret


def test_only_hash_is_stored_and_it_matches_in_constant_time() -> None:
    token = RefreshToken.new(new_id().hex)
    assert token.hash == hashlib.sha256(token.secret.encode()).digest()
    assert token.matches(token.hash)
    assert not token.matches(RefreshToken.new(token.session_id).hash)
    assert not token.matches(None)
    assert token.secret not in repr(token)


def test_parse_roundtrip() -> None:
    token = RefreshToken.new(new_id().hex)
    assert RefreshToken.parse(str(token)) == token
    assert RefreshToken.parse(f"  {token}\n") == token


@pytest.mark.parametrize(
    "raw",
    ["", "abc", f"{new_id().hex}.", f"{new_id().hex}.short", "x" * 32 + "." + "a" * 43,
     f"{new_id().hex}:{'a' * 43}", f"{new_id().hex}.{'a' * 42}!"],
)  # fmt: skip
def test_garbage_refresh_token_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidRefreshTokenError):
        RefreshToken.parse(raw)
