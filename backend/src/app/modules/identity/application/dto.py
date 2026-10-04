"""Результаты и входные данные use cases identity (ADR-0020 §3)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.api import Action
from app.modules.identity.domain.consent import Consent, ConsentDocument
from app.modules.identity.domain.restriction import Restriction, RestrictionKind, RestrictionSource
from app.modules.identity.domain.session import SessionId
from app.modules.identity.domain.user import User, UserIntent, UserStatus
from app.platform.kernel.ids import CaseId, CityId, RestrictionId, UserId
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
    me: MeView
    """Свой профиль на момент входа: ответ /auth/telegram без чтений после commit."""
    access: AccessView


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
    show_telegram: bool = True
    """«Показывать после договорённости»: свой Telegram (S43, 6.5)."""

    @classmethod
    def of(cls, user: User, *, deletion_scheduled_at: datetime | None) -> MeView:
        """Из загруженного агрегата: вход уже держит его в своей транзакции."""
        return cls(
            id=user.id,
            display_name=user.display_name,
            ui_locale=user.ui_locale,
            trust_level=user.trust_level,
            phone_verified=user.phone_verified_at is not None,
            created_at=user.created_at,
            version=user.version,
            home_city_id=user.home_city_id,
            intent=user.intent,
            deletion_scheduled_at=deletion_scheduled_at,
            show_telegram=user.privacy.show_telegram,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class MeState:
    """Свой профиль и то, из чего считается AccessView, — одним запросом (GET /me)."""

    me: MeView
    restrictions: list[Restriction]
    """Неснятые санкции, которые действуют сейчас или начнутся позже."""
    consents: list[Consent]


@dataclass(frozen=True, slots=True, kw_only=True)
class LoginState:
    """Что вход дочитывает в своей транзакции одним запросом: роли — в токен, согласия и ждущее
    удаление — в ответ /auth/telegram."""

    roles: frozenset[Role]
    consents: list[Consent]
    deletion_scheduled_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessView:
    """Что пользователю можно сейчас (GET /me): онбординг и экран ограничения по нему."""

    consents: Mapping[ConsentDocument, str]
    """Принятые версии документов (последняя по каждому)."""
    consent_required: bool
    """Нет согласия с действующими версиями правил, 18+ или политики: нужен S02c."""
    allowed: frozenset[Action]
    """Действия, которые не запрещены санкциями и согласиями."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StaffCredentialsSet:
    """Итог `cli staff-create`: секрет TOTP показывается один раз и нигде не хранится, кроме БД
    (там — зашифрованным, 8.4)."""

    user_id: UserId
    login: str
    totp_secret: str
    totp_uri: str
    replaced: bool
    """True — у сотрудника уже был вход: пароль и TOTP заменены."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StaffTotpReencrypted:
    """Итог `cli staff-totp-reencrypt` (8.4): сколько секретов перешифровано текущим ключом."""

    reencrypted: int
    """Были под прежним ключом или открытыми (строки до 8.4)."""
    current: int
    """Уже под текущим ключом — не тронуты."""
    undecryptable: tuple[UserId, ...]
    """Не расшифровать ни текущим, ни прежним ключом: строки не тронуты, сотруднику — заново
    `cli staff-create`."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RestrictionRecord:
    """Санкция в карточке пользователя для персонала (Admin API, 2.7b): и снятые — для истории."""

    id: RestrictionId
    kind: RestrictionKind
    reason_code: str
    source: RestrictionSource
    case_id: CaseId | None
    starts_at: datetime
    ends_at: datetime | None
    lifted_at: datetime | None
    created_by: UserId | None


@dataclass(frozen=True, slots=True, kw_only=True)
class StaffUserCard:
    """Карточка пользователя персоналу без ПД: статус, доверие, активность, роли, санкции."""

    id: UserId
    status: UserStatus
    trust_level: int
    ui_locale: Locale
    home_city_id: CityId | None
    intent: UserIntent | None
    phone_verified: bool
    roles: frozenset[Role]
    created_at: datetime
    last_seen_at: datetime | None
    last_login_at: datetime | None
    deleted_at: datetime | None
    trust_penalty_at: datetime | None
    completed_deals: int
    active_sessions: int
    restrictions: tuple[RestrictionRecord, ...]
    """Новые первыми, вместе со снятыми и истёкшими."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PersonalData:
    """ПД пользователя — только support и admin, каждый просмотр — в audit_log (§13.2, §13.4)."""

    display_name: str
    phone_e164: str | None
    telegram_id: int | None
    telegram_username: str | None
    telegram_name: str | None
    """Имя и фамилия из профиля Telegram на момент последнего входа."""

    FIELDS = ("display_name", "phone_e164", "telegram_id", "telegram_username", "telegram_name")
    """Что попадает в `changes.fields` записи аудита о просмотре."""
