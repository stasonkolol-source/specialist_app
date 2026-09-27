"""Access JWT (ADR-0009, ARCHITECTURE §8.2): EdDSA (Ed25519), `kid` с первого дня.

Ключи — в `JWT_KEYS`: `kid:ключ,kid:ключ`, ключ — base64url 32 байт приватного Ed25519.
Первый ключ подписывает, остальные только проверяют: после ротации (`cli jwt-keys
--rotate`) старый ключ живёт в списке, пока не истекут выданные им токены (15 минут).

Клеймы: `sub` (user_id), `sid` (сессия), `plat`, `amr`, `tl`, `roles` (только у персонала),
`iss`, `iat`, `exp`. Время проверяем по порту Clock, а не часами pyjwt.
"""

import base64
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId
from app.platform.kernel.principal import Platform, Principal, Role
from app.platform.security.errors import InvalidTokenError, TokenExpiredError

ALGORITHM = "EdDSA"
REQUIRED_CLAIMS = ("iss", "sub", "sid", "plat", "amr", "tl", "iat", "exp")


class JwtKeysError(ValueError):
    """JWT_KEYS не задан или испорчен — web не должен стартовать."""


@dataclass(frozen=True, slots=True)
class SigningKey:
    kid: str
    private: Ed25519PrivateKey = field(repr=False)

    @property
    def public(self) -> Ed25519PublicKey:
        return self.private.public_key()

    @classmethod
    def generate(cls, kid: str | None = None) -> SigningKey:
        return cls(kid=kid or f"k{secrets.token_hex(4)}", private=Ed25519PrivateKey.generate())

    def dump(self) -> str:
        raw = self.private.private_bytes_raw()
        return f"{self.kid}:{base64.urlsafe_b64encode(raw).decode().rstrip('=')}"


@dataclass(frozen=True, slots=True)
class JwtKeys:
    signing: SigningKey
    verifying: dict[str, Ed25519PublicKey]

    @classmethod
    def parse(cls, value: str) -> JwtKeys:
        keys = [_parse_key(item.strip()) for item in value.split(",") if item.strip()]
        if not keys:
            raise JwtKeysError("JWT_KEYS is empty: run `make cli ARGS=jwt-keys`")
        kids = [key.kid for key in keys]
        if len(set(kids)) != len(kids):
            raise JwtKeysError("JWT_KEYS: duplicate kid")
        return cls(signing=keys[0], verifying={key.kid: key.public for key in keys})

    @classmethod
    def of(cls, *keys: SigningKey) -> JwtKeys:
        return cls(signing=keys[0], verifying={key.kid: key.public for key in keys})


def _parse_key(item: str) -> SigningKey:
    kid, sep, encoded = item.partition(":")
    if not sep or not kid or not encoded:
        raise JwtKeysError("JWT_KEYS: expected kid:key pairs separated by commas")
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        private = Ed25519PrivateKey.from_private_bytes(raw)
    except ValueError as exc:
        raise JwtKeysError(f"JWT_KEYS: key {kid} is not a raw Ed25519 private key") from exc
    return SigningKey(kid=kid, private=private)


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessClaims:
    user_id: UserId
    session_id: str
    platform: Platform
    amr: tuple[str, ...]
    trust_level: int
    roles: frozenset[Role]
    issued_at: datetime
    expires_at: datetime

    def principal(self) -> Principal:
        return Principal(
            user_id=self.user_id,
            trust_level=self.trust_level,
            roles=self.roles,
            platform=self.platform,
            session_id=self.session_id,
        )


class AccessTokens:
    """Выпуск и проверка access-токенов одного окружения."""

    def __init__(self, keys: JwtKeys, clock: Clock, *, issuer: str, ttl: timedelta) -> None:
        self._keys = keys
        self._clock = clock
        self._issuer = issuer
        self._ttl = ttl

    def issue(self, principal: Principal, *, amr: tuple[str, ...]) -> tuple[str, datetime]:
        if principal.session_id is None:
            raise ValueError("access token needs a session")
        now = self._clock.now().replace(microsecond=0)
        expires_at = now + self._ttl
        claims: dict[str, Any] = {
            "iss": self._issuer,
            "sub": str(principal.user_id),
            "sid": principal.session_id,
            "plat": principal.platform.value,
            "amr": list(amr),
            "tl": principal.trust_level,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        if principal.roles:
            claims["roles"] = sorted(role.value for role in principal.roles)
        token = jwt.encode(
            claims,
            self._keys.signing.private,
            algorithm=ALGORITHM,
            headers={"kid": self._keys.signing.kid},
        )
        return token, expires_at

    def decode(self, token: str) -> AccessClaims:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            key = self._keys.verifying.get(kid) if isinstance(kid, str) else None
            if key is None:
                raise InvalidTokenError
            claims = jwt.decode(
                token,
                key,
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                options={
                    "require": list(REQUIRED_CLAIMS),
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                },
            )
        except jwt.PyJWTError as exc:
            raise InvalidTokenError from exc
        return self._claims(claims)

    def _claims(self, claims: dict[str, Any]) -> AccessClaims:
        try:
            issued_at = datetime.fromtimestamp(int(claims["iat"]), tz=UTC)
            expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
            result = AccessClaims(
                user_id=UserId(UUID(str(claims["sub"]))),
                session_id=str(claims["sid"]),
                platform=Platform(claims["plat"]),
                amr=tuple(str(item) for item in claims["amr"]),
                trust_level=int(claims["tl"]),
                roles=frozenset(Role(role) for role in claims.get("roles", [])),
                issued_at=issued_at,
                expires_at=expires_at,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidTokenError from exc
        if self._clock.now() >= result.expires_at:
            raise TokenExpiredError
        return result
