"""Access JWT: EdDSA, kid, ротация ключей (DEVELOPMENT_PLAN 0.14, ADR-0009)."""

import base64
import json
from datetime import timedelta

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key

from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.principal import Platform, Principal, Role
from app.platform.security.errors import InvalidTokenError, TokenExpiredError
from app.platform.security.jwt import AccessTokens, JwtKeys, JwtKeysError, SigningKey
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

TTL = timedelta(minutes=15)
KEY = SigningKey.generate("k1")
OLD_KEY = SigningKey.generate("k0")


def tokens(clock: FakeClock, *keys: SigningKey, issuer: str = "sosed") -> AccessTokens:
    return AccessTokens(JwtKeys.of(*(keys or (KEY,))), clock, issuer=issuer, ttl=TTL)


def principal(**overrides: object) -> Principal:
    values: dict[str, object] = {
        "user_id": UserId(new_id()),
        "trust_level": 1,
        "platform": Platform.TMA,
        "session_id": new_id().hex,
    }
    return Principal(**(values | overrides))  # type: ignore[arg-type]


def _segments(token: str) -> list[dict[str, object]]:
    head, body, _ = token.split(".")
    return [json.loads(base64.urlsafe_b64decode(part + "==")) for part in (head, body)]


def _forge(token: str, **claims: object) -> str:
    head, body, signature = token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(body + "==")) | claims
    forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{head}.{forged}.{signature}"


def test_roundtrip_gives_principal_back() -> None:
    clock = FakeClock()
    who = principal(trust_level=2, platform=Platform.IOS)
    token, expires_at = tokens(clock).issue(who, amr=("tg_webapp",))

    claims = tokens(clock).decode(token)
    assert claims.principal() == who
    assert claims.amr == ("tg_webapp",)
    assert expires_at == clock.now().replace(microsecond=0) + TTL
    header, payload = _segments(token)
    assert header == {"alg": "EdDSA", "kid": "k1", "typ": "JWT"}
    assert set(payload) == {"iss", "sub", "sid", "plat", "amr", "tl", "iat", "exp"}


def test_roles_are_present_only_for_staff() -> None:
    clock = FakeClock()
    staff = principal(roles=frozenset({Role.MODERATOR, Role.SUPPORT}))
    token, _ = tokens(clock).issue(staff, amr=("pwd", "otp"))
    assert _segments(token)[1]["roles"] == ["moderator", "support"]
    assert tokens(clock).decode(token).roles == staff.roles


def test_token_expires_after_ttl() -> None:
    clock = FakeClock()
    token, _ = tokens(clock).issue(principal(), amr=("tg_webapp",))
    clock.advance(TTL - timedelta(seconds=1))
    tokens(clock).decode(token)
    clock.advance(timedelta(seconds=1))
    with pytest.raises(TokenExpiredError):
        tokens(clock).decode(token)


def test_unknown_kid_is_rejected() -> None:
    clock = FakeClock()
    token, _ = tokens(clock, OLD_KEY).issue(principal(), amr=("tg_webapp",))
    with pytest.raises(InvalidTokenError):
        tokens(clock, KEY).decode(token)


def test_signature_of_other_key_with_same_kid_is_rejected() -> None:
    clock = FakeClock()
    impostor = SigningKey(kid="k1", private=SigningKey.generate().private)
    token, _ = tokens(clock, impostor).issue(principal(), amr=("tg_webapp",))
    with pytest.raises(InvalidTokenError):
        tokens(clock, KEY).decode(token)


@pytest.mark.parametrize(
    "claims",
    [{"sub": str(new_id())}, {"tl": 3}, {"roles": ["admin"]}, {"exp": 4_102_444_800}],
    ids=["other-user", "trust-level", "roles", "exp"],
)
def test_tampered_payload_is_rejected(claims: dict[str, object]) -> None:
    clock = FakeClock()
    token, _ = tokens(clock).issue(principal(), amr=("tg_webapp",))
    with pytest.raises(InvalidTokenError):
        tokens(clock).decode(_forge(token, **claims))


def test_algorithm_confusion_is_rejected() -> None:
    clock = FakeClock()
    payload = {
        "iss": "sosed", "sub": str(new_id()), "sid": new_id().hex, "plat": "tma",
        "amr": ["tg_webapp"], "tl": 3, "iat": 0, "exp": 4_102_444_800,
    }  # fmt: skip
    none_token = pyjwt.encode(payload, None, algorithm="none", headers={"kid": "k1"})
    hs_token = pyjwt.encode(payload, "k1-guess" * 4, algorithm="HS256", headers={"kid": "k1"})
    es_token = pyjwt.encode(
        payload, generate_private_key(SECP256R1()), algorithm="ES256", headers={"kid": "k1"}
    )
    for token in (none_token, hs_token, es_token):
        with pytest.raises(InvalidTokenError):
            tokens(clock).decode(token)


def test_other_issuer_is_rejected() -> None:
    clock = FakeClock()
    token, _ = tokens(clock, issuer="sosed-stage").issue(principal(), amr=("tg_webapp",))
    with pytest.raises(InvalidTokenError):
        tokens(clock, issuer="sosed").decode(token)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "Bearer x.y.z"])
def test_garbage_is_rejected(token: str) -> None:
    with pytest.raises(InvalidTokenError):
        tokens(FakeClock()).decode(token)


def test_rotation_keeps_old_tokens_valid() -> None:
    clock = FakeClock()
    before, _ = tokens(clock, OLD_KEY).issue(principal(), amr=("tg_webapp",))
    rotated = tokens(clock, KEY, OLD_KEY)
    after, _ = rotated.issue(principal(), amr=("tg_webapp",))
    assert _segments(after)[0]["kid"] == "k1"
    rotated.decode(before)
    rotated.decode(after)


def test_keys_roundtrip_through_env_value() -> None:
    value = ",".join([KEY.dump(), OLD_KEY.dump()])
    keys = JwtKeys.parse(value)
    assert keys.signing.kid == "k1"
    assert set(keys.verifying) == {"k1", "k0"}
    assert repr(KEY).count("private") == 0


@pytest.mark.parametrize(
    "value", ["", "k1", "k1:", ":abc", "k1:not-base64!", "k1:AAAA", f"{KEY.dump()},{KEY.dump()}"]
)
def test_broken_keys_value_is_reported(value: str) -> None:
    with pytest.raises(JwtKeysError):
        JwtKeys.parse(value)


def test_issuing_needs_a_session() -> None:
    with pytest.raises(ValueError, match="session"):
        tokens(FakeClock()).issue(principal(session_id=None), amr=("tg_webapp",))
