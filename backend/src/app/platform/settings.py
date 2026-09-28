"""Настройки всех процессов (ADR-0020 §10): группы pydantic-settings с env_prefix.

Правила:
- Настройки читаются только здесь. Остальной код получает группы через DI (Scope.APP),
  а application — frozen dataclass `<Модуль>Config`, собранный в di.py модуля.
- Секреты — `SecretStr`: в repr и логах их значения не видны.
- Переменные окружения важнее `backend/.env`. Путь к `.env` абсолютный от этого файла,
  поэтому `.env` находится из любого рабочего каталога.
- Новая настройка появляется в `backend/.env.example` в том же шаге (это проверяет тест).
"""

import re
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


_TELEGRAM_USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")
"""Имя пользователя Telegram: 5–32 символа, начинается с буквы."""


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGE = "stage"
    PRODUCTION = "production"


class SettingsError(RuntimeError):
    """Настройки неполны или неверны — процесс не должен стартовать."""


class _Group(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        frozen=True,
    )


class AppSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="APP_")

    env: Environment = Environment.DEV
    name: str = "Соседи"
    """Имя продукта в текстах сервера (`{{appName}}` правовых документов); для sr-Latn —
    транслитом. Код продукта остаётся specialist_app."""
    log_level: str = "INFO"
    log_json: bool = True
    release: str = "dev"
    heartbeat_url: str | None = None
    """Ping Healthchecks.io раз в минуту из воркера (K33), без адреса — только лог."""
    web_host: str = "127.0.0.1"
    """Адрес uvicorn: локально — только loopback; в контейнере — 0.0.0.0 (за kamal-proxy)."""
    web_port: int = Field(default=8000, ge=1, le=65535)
    api_public_url: str = "http://127.0.0.1:8000"
    """Публичный адрес API: из него строится `type` ошибок RFC 9457."""
    min_client_versions: dict[str, str] = Field(default_factory=dict)
    """Минимальные версии клиентов для 426, JSON: {"tma": "1.0.0"}. С 1.1 — из client-config."""

    @field_validator("min_client_versions")
    @classmethod
    def _versions(cls, value: dict[str, str]) -> dict[str, str]:
        for platform, version in value.items():
            if not re.fullmatch(r"[a-z]+", platform) or not re.fullmatch(
                r"\d+(\.\d+){0,2}", version
            ):
                raise ValueError(f"bad min client version {platform}={version}")
        return value


class DbSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="DB_")

    dsn: SecretStr
    migrator_dsn: SecretStr | None = None
    pool_size: int = Field(default=10, ge=1)
    pool_max_overflow: int = Field(default=5, ge=0)
    echo: bool = False


class ValkeySettings(_Group):
    model_config = SettingsConfigDict(env_prefix="VALKEY_")

    url: SecretStr


class TelegramSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_")

    bot_token: SecretStr
    bot_username: str
    webhook_secret: SecretStr | None = None
    mini_app_url: str | None = None
    use_test_environment: bool = False
    support_username: str | None = None
    """Аккаунт поддержки для /help (K23, Q25), без `@`; пусто — «контакт появится скоро»."""

    @field_validator("support_username")
    @classmethod
    def _support_username(cls, value: str | None) -> str | None:
        username = (value or "").strip().removeprefix("@")
        if not username:
            return None
        if not _TELEGRAM_USERNAME.fullmatch(username):
            raise ValueError("TELEGRAM_SUPPORT_USERNAME: 5–32 символа [A-Za-z0-9_], без @")
        return username


class JwtSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="JWT_")

    issuer: str = "sosed"
    access_ttl_seconds: int = Field(default=900, ge=60)
    refresh_ttl_days: int = Field(default=30, ge=1)
    """Мобильные приложения; Mini App — refresh_ttl_days_tma (ADR-0009)."""
    refresh_ttl_days_tma: int = Field(default=7, ge=1)
    keys: SecretStr | None = None
    """`kid:ключ,kid:ключ` (Ed25519, base64url); первый подписывает. Создаёт `cli jwt-keys`."""


class S3Settings(_Group):
    model_config = SettingsConfigDict(env_prefix="S3_")

    endpoint_url: str | None = None
    region: str = "auto"
    access_key_id: SecretStr | None = None
    secret_access_key: SecretStr | None = None
    bucket_incoming: str = "incoming"
    bucket_media: str = "media"
    bucket_private: str = "private"
    public_base_url: str | None = None
    public_endpoint_url: str | None = None
    """Адрес S3, доступный телефону: им подписываются presigned-ссылки (dev — туннель Garage)."""


class SentrySettings(_Group):
    model_config = SettingsConfigDict(env_prefix="SENTRY_")

    dsn: SecretStr | None = None
    traces_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class AiSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="AI_")

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None


class AnalyticsSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="ANALYTICS_")

    posthog_api_key: SecretStr | None = None
    posthog_host: str = "https://eu.i.posthog.com"


TODO_PREFIX = "[TODO"
"""Значение-заглушка: владелец ещё не решил. На проде процесс с заглушкой не стартует."""


class LegalSettings(_Group):
    """Подстановки правовых документов (DEVELOPMENT_PLAN 1.5a): `{{OPERATOR_NAME}}`,
    `{{CONTACT_EMAIL}}` в backend/content/legal. Заглушки видны в тексте на dev и stage."""

    model_config = SettingsConfigDict(env_prefix="LEGAL_")

    operator_name: str = "[TODO K22: оператор данных — решает владелец, ADR-0018]"
    contact_email: str = "[TODO K22: почта поддержки — решает владелец, K23]"

    def todo_fields(self) -> list[str]:
        """Поля, где осталась заглушка [TODO …]: переменные окружения для сообщения об ошибке."""
        prefix = str(self.model_config.get("env_prefix", ""))
        return [
            prefix + name.upper()
            for name in type(self).model_fields
            if str(getattr(self, name)).startswith(TODO_PREFIX)
        ]


GROUPS: tuple[type[_Group], ...] = (
    AppSettings,
    DbSettings,
    ValkeySettings,
    TelegramSettings,
    JwtSettings,
    S3Settings,
    SentrySettings,
    AiSettings,
    AnalyticsSettings,
    LegalSettings,
)


class Settings:
    """Все группы настроек процесса. Создаётся один раз в entrypoint и кладётся в DI."""

    def __init__(self, env_file: Path | None = ENV_FILE) -> None:
        values: dict[type[_Group], _Group] = {}
        missing: list[str] = []
        invalid: list[str] = []
        for group in GROUPS:
            try:
                values[group] = group(_env_file=env_file)  # type: ignore[call-arg]  # параметр pydantic-settings
            except ValidationError as exc:
                prefix = str(group.model_config.get("env_prefix", ""))
                for error in exc.errors():
                    name = prefix + str(error["loc"][0]).upper()
                    (missing if error["type"] == "missing" else invalid).append(name)
        if missing or invalid:
            parts = []
            if missing:
                parts.append("не заданы: " + ", ".join(missing))
            if invalid:
                parts.append("неверные значения: " + ", ".join(invalid))
            raise SettingsError("Настройки неполны — " + "; ".join(parts))
        self.app = _as(values, AppSettings)
        self.db = _as(values, DbSettings)
        self.valkey = _as(values, ValkeySettings)
        self.telegram = _as(values, TelegramSettings)
        self.jwt = _as(values, JwtSettings)
        self.s3 = _as(values, S3Settings)
        self.sentry = _as(values, SentrySettings)
        self.ai = _as(values, AiSettings)
        self.analytics = _as(values, AnalyticsSettings)
        self.legal = _as(values, LegalSettings)
        if self.app.env is Environment.PRODUCTION and (todo := self.legal.todo_fields()):
            # оператор и почта попадают в политику конфиденциальности: заглушка на проде — нарушение
            raise SettingsError("Настройки неполны — на проде нужны значения: " + ", ".join(todo))


def _as[T: _Group](values: dict[type[_Group], _Group], group: type[T]) -> T:
    value = values[group]
    assert isinstance(value, group)  # noqa: S101 — инвариант сборки выше
    return value


def env_names(group: type[_Group]) -> list[str]:
    """Имена переменных окружения группы — для .env.example и проверок."""
    prefix = str(group.model_config.get("env_prefix", ""))
    return [prefix + name.upper() for name in group.model_fields]


def describe(settings: Settings) -> dict[str, Any]:
    """Сводка настроек без секретов — для логов старта."""
    return {
        "env": settings.app.env.value,
        "release": settings.app.release,
        "db_pool_size": settings.db.pool_size,
        "telegram_bot": settings.telegram.bot_username,
        "s3_endpoint": settings.s3.endpoint_url,
        "sentry": settings.sentry.dsn is not None,
    }
