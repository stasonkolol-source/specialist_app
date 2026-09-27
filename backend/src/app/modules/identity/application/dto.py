"""Результаты и входные данные use cases identity (ADR-0020 §3)."""

from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.domain.session import SessionId
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class TelegramProfile:
    """Пользователь из проверенного initData (platform/security/initdata.py)."""

    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_premium: bool = False
    allows_write_to_pm: bool = False
    photo_url: str | None = None

    def snapshot(self) -> dict[str, object]:
        """Снимок для auth_identities.profile: только то, что прислал Telegram."""
        values: dict[str, object] = {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "username": self.username,
            "language_code": self.language_code,
            "is_premium": self.is_premium,
            "allows_write_to_pm": self.allows_write_to_pm,
            "photo_url": self.photo_url,
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionTokens:
    """Пара токенов для клиента. refresh_token — секрет: не логируется."""

    user_id: UserId
    session_id: SessionId
    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthResult:
    tokens: SessionTokens
    is_new: bool
