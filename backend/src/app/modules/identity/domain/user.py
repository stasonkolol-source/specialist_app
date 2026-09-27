"""Пользователь и способы входа (ADR-0009, ARCHITECTURE §7.3).

«Клиент» и «исполнитель» — не роли, а возможности аккаунта; намерение из онбординга
(`intent`) лишь настраивает интерфейс. Статус аккаунта — только `active` и `deleted`:
приостановки и баны — записи `restrictions`, а не статус. Способы входа
(`auth_identities`) входят в агрегат: вход обновляет снимок профиля.
"""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.modules.identity.domain.trust import TrustLevel
from app.modules.identity.errors import (
    AccountDeletedError,
    InvalidDisplayNameError,
    UserAlreadyDeletedError,
)
from app.platform.contracts.events.identity import EntryPoint, UserRegistered, UserUpdated
from app.platform.kernel.aggregate import StatusChange, VersionedAggregate
from app.platform.kernel.errors import ConflictError, ProgrammingError
from app.platform.kernel.ids import CityId, UserId, new_id
from app.platform.kernel.localized import Locale

MAX_DISPLAY_NAME = 64
DEFAULT_TIMEZONE = "Europe/Belgrade"
FALLBACK_DISPLAY_NAME = "Сосед"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


_ALLOWED: Final[Mapping[UserStatus, frozenset[UserStatus]]] = {
    UserStatus.ACTIVE: frozenset({UserStatus.DELETED}),
    UserStatus.DELETED: frozenset(),
}


class UserIntent(StrEnum):
    """«Что вы хотите?» в онбординге S02b: стартовый экран и подсказки, не права."""

    CLIENT = "client"
    """Найти мастера."""
    PRO = "pro"
    """Я специалист: профиль `pro` в каталоге."""
    CASUAL = "casual"
    """Ищу подработку: профиль `casual`, задачи рядом."""


class AuthProvider(StrEnum):
    TELEGRAM = "telegram"
    APPLE = "apple"
    GOOGLE = "google"
    PHONE = "phone"
    EMAIL = "email"


_LOCALE_BY_LANGUAGE: Final[Mapping[str, Locale]] = {
    "ru": Locale.RU,
    "uk": Locale.RU,
    "be": Locale.RU,
    "kk": Locale.RU,
    "sr": Locale.SR_LATN,
    "hr": Locale.SR_LATN,
    "bs": Locale.SR_LATN,
    "me": Locale.SR_LATN,
    "en": Locale.EN,
}
"""Язык клиента Telegram → язык интерфейса. СНГ — русский, сербский — латиница (§7.4)."""

_CONTROL = re.compile(r"[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")


def locale_from_language(language_code: str | None) -> Locale:
    if not language_code:
        return Locale.RU
    return _LOCALE_BY_LANGUAGE.get(language_code.lower().split("-")[0], Locale.RU)


def normalize_display_name(*parts: str | None) -> str:
    """Имя для показа: без управляющих символов и bidi-override, пробелы схлопнуты."""
    raw = " ".join(part for part in parts if part)
    text = _CONTROL.sub("", unicodedata.normalize("NFC", raw))
    return " ".join(text.split())[:MAX_DISPLAY_NAME].strip()


def clean_display_name(*parts: str | None) -> str:
    """Имя из профиля провайдера; пустое заменяется нейтральным «Сосед»."""
    return normalize_display_name(*parts) or FALLBACK_DISPLAY_NAME


@dataclass(kw_only=True)
class AuthIdentity:
    """Способ входа внутри агрегата. Равенство по полям: снимок UoW сравнивает состояние."""

    id: UUID
    provider: AuthProvider
    subject: str
    profile: dict[str, object]
    created_at: datetime
    last_login_at: datetime | None = None


@dataclass(eq=False, kw_only=True)
class User(VersionedAggregate):
    id: UserId
    status: UserStatus
    display_name: str
    ui_locale: Locale
    timezone: str
    trust_level: int
    created_at: datetime
    identities: list[AuthIdentity]
    home_city_id: CityId | None = None
    """Город из онбординга (geo.cities); существование и статус проверяет use case."""
    intent: UserIntent | None = None
    phone_e164: str | None = None
    phone_verified_at: datetime | None = None
    last_seen_at: datetime | None = None
    deleted_at: datetime | None = None
    _history: list[StatusChange[UserStatus]] = field(default_factory=list, init=False, repr=False)

    @classmethod
    def register(
        cls,
        *,
        provider: AuthProvider,
        subject: str,
        profile: Mapping[str, object],
        display_name: str,
        ui_locale: Locale,
        now: datetime,
        entry_point: EntryPoint | None = None,
        start_param: str | None = None,
    ) -> User:
        """Новый аккаунт. `entry_point` и `start_param` — первое касание (атрибуция в growth)."""
        user = cls(
            id=UserId(new_id()),
            status=UserStatus.ACTIVE,
            display_name=clean_display_name(display_name),
            ui_locale=ui_locale,
            timezone=DEFAULT_TIMEZONE,
            trust_level=0,
            created_at=now,
            identities=[
                AuthIdentity(
                    id=new_id(),
                    provider=provider,
                    subject=subject,
                    profile=dict(profile),
                    created_at=now,
                    last_login_at=now,
                )
            ],
            last_seen_at=now,
            version=1,
        )
        user._record(
            UserRegistered(
                user_id=user.id,
                provider=provider.value,
                entry_point=entry_point,
                start_param=start_param,
                occurred_at=now,
            )
        )
        return user

    def record_login(
        self, *, provider: AuthProvider, subject: str, profile: Mapping[str, object], now: datetime
    ) -> None:
        """Повторный вход: свежий снимок профиля провайдера и время входа."""
        self.ensure_active()
        identity = self.identity(provider, subject)
        identity.profile = dict(profile)
        identity.last_login_at = now
        self.last_seen_at = now

    def update_profile(
        self,
        *,
        now: datetime,
        display_name: str | None = None,
        ui_locale: Locale | None = None,
        home_city_id: CityId | None = None,
        intent: UserIntent | None = None,
    ) -> None:
        """Имя, язык интерфейса, город и намерение; None — поле не меняется."""
        self.ensure_active()
        changed: list[str] = []
        if display_name is not None:
            name = normalize_display_name(display_name)
            if not name:
                raise InvalidDisplayNameError(field="display_name")
            if name != self.display_name:
                self.display_name = name
                changed.append("display_name")
        if ui_locale is not None and ui_locale is not self.ui_locale:
            self.ui_locale = ui_locale
            changed.append("ui_locale")
        if home_city_id is not None and home_city_id != self.home_city_id:
            self.home_city_id = home_city_id
            changed.append("home_city_id")
        if intent is not None and intent is not self.intent:
            self.intent = intent
            changed.append("intent")
        if changed:
            self._record(UserUpdated(user_id=self.id, fields=tuple(changed), occurred_at=now))

    def reset_onboarding(self, *, now: datetime) -> None:
        """Онбординг заново (dev, `cli dev-reset-user`): без города и намерения, язык — снова
        из клиента Telegram, как при регистрации. Согласия отзывает use case."""
        self.ensure_active()
        telegram = next((i for i in self.identities if i.provider is AuthProvider.TELEGRAM), None)
        language = telegram.profile.get("language_code") if telegram else None
        locale = locale_from_language(language if isinstance(language, str) else None)
        changed = [
            name
            for name, differs in (
                ("home_city_id", self.home_city_id is not None),
                ("intent", self.intent is not None),
                ("ui_locale", self.ui_locale is not locale),
            )
            if differs
        ]
        self.home_city_id = None
        self.intent = None
        self.ui_locale = locale
        if changed:
            self._record(UserUpdated(user_id=self.id, fields=tuple(changed), occurred_at=now))

    def apply_trust_level(self, level: TrustLevel, *, now: datetime) -> None:
        """Записать пересчитанный уровень доверия (политика `trust_level`, §13.2)."""
        self.ensure_active()
        if level != self.trust_level:
            self.trust_level = int(level)
            self._record(UserUpdated(user_id=self.id, fields=("trust_level",), occurred_at=now))

    def identity(self, provider: AuthProvider, subject: str) -> AuthIdentity:
        for identity in self.identities:
            if identity.provider is provider and identity.subject == subject:
                return identity
        raise ProgrammingError(f"user {self.id} has no identity {provider}:{subject}")

    def ensure_active(self) -> None:
        if self.status is UserStatus.DELETED:
            raise AccountDeletedError(user_id=self.id)

    def delete(self, *, by: UserId | None, now: datetime, reason: str | None = None) -> None:
        self._move_to(
            UserStatus.DELETED, error=UserAlreadyDeletedError, by=by, now=now, reason=reason
        )
        self.deleted_at = now

    def pull_history(self) -> list[StatusChange[UserStatus]]:
        history, self._history = self._history, []
        return history

    def _move_to(
        self,
        target: UserStatus,
        *,
        error: type[ConflictError],
        by: UserId | None,
        now: datetime,
        reason: str | None = None,
    ) -> None:
        if target not in _ALLOWED[self.status]:
            raise error(user_id=self.id, status=self.status, target=target)
        self._history.append(
            StatusChange(from_=self.status, to=target, actor_id=by, reason=reason, at=now)
        )
        self.status = target
