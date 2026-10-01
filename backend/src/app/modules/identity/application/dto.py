"""Результаты и входные данные use cases identity (ADR-0020 §3)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.api import Action
from app.modules.identity.domain.consent import ConsentDocument
from app.modules.identity.domain.session import SessionId
from app.modules.identity.domain.user import UserIntent
from app.platform.kernel.ids import CityId, UserId
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Role


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


@dataclass(frozen=True, slots=True, kw_only=True)
class StaffRoleGranted:
    """Итог `cli staff-grant`: кому выдана роль; `granted` False — роль уже была."""

    user_id: UserId
    role: Role
    granted: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class OnboardingReset:
    """Итог `cli dev-reset-user`: чей онбординг сброшен и сколько согласий отозвано."""

    user_id: UserId
    withdrawn_consents: int


@dataclass(frozen=True, slots=True, kw_only=True)
class MeView:
    """Свой профиль для GET /me; version — ETag для PATCH /me."""

    id: UserId
    display_name: str
    ui_locale: Locale
    trust_level: int
    phone_verified: bool
    created_at: datetime
    version: int
    home_city_id: CityId | None = None
    intent: UserIntent | None = None
    deletion_scheduled_at: datetime | None = None
    """Аккаунт удалится тогда (ждущий запрос на удаление); None — запроса нет."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessView:
    """Что пользователю можно сейчас (GET /me): онбординг и экран ограничения по нему."""

    consents: Mapping[ConsentDocument, str]
    """Принятые версии документов (последняя по каждому)."""
    consent_required: bool
    """Нет согласия с действующими версиями правил, 18+ или политики: нужен S02c."""
    allowed: frozenset[Action]
    """Действия, которые не запрещены санкциями и согласиями."""
