"""Refresh-токены (ADR-0009): 256 бит случайности, в БД — только SHA-256.

Формат `<session_id>.<secret>`: сессия находится по первичному ключу, а сверка хэша
секрета с текущим хэшем сессии отличает свежий токен от повторного. Правила ротации
(каждое использование выдаёт новый токен; повтор старого отзывает всю сессию; окно
гонки для только что заменённого токена) живут в агрегате сессии модуля identity
(шаг 0.15a), здесь — только сам токен.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field

from app.platform.security.errors import InvalidRefreshTokenError

SECRET_BYTES = 32
_TOKEN = re.compile(r"(?P<session>[0-9a-f]{32})\.(?P<secret>[A-Za-z0-9_-]{43})")


def hash_secret(secret: str) -> bytes:
    return hashlib.sha256(secret.encode()).digest()


@dataclass(frozen=True, slots=True)
class RefreshToken:
    session_id: str
    secret: str = field(repr=False)

    @classmethod
    def new(cls, session_id: str) -> RefreshToken:
        return cls(session_id=session_id, secret=secrets.token_urlsafe(SECRET_BYTES))

    @classmethod
    def parse(cls, raw: str) -> RefreshToken:
        match = _TOKEN.fullmatch(raw.strip())
        if match is None:
            raise InvalidRefreshTokenError
        return cls(session_id=match["session"], secret=match["secret"])

    @property
    def hash(self) -> bytes:
        return hash_secret(self.secret)

    def matches(self, stored_hash: bytes | None) -> bool:
        return stored_hash is not None and hmac.compare_digest(self.hash, stored_hash)

    def __str__(self) -> str:
        return f"{self.session_id}.{self.secret}"
