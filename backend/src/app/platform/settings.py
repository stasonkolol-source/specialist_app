"""Настройки всех процессов (ADR-0020 §10): группы pydantic-settings с env_prefix.

Правила:
- Настройки читаются только здесь. Остальной код получает группы через DI (Scope.APP),
  а application — frozen dataclass `<Модуль>Config`, собранный в di.py модуля.
- Секреты — `SecretStr`: в repr и логах их значения не видны.
- Переменные окружения важнее `backend/.env`. Путь к `.env` абсолютный от этого файла,
  поэтому `.env` находится из любого рабочего каталога.
- Новая настройка появляется в `backend/.env.example` в том же шаге (это проверяет тест).
"""

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


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
    log_level: str = "INFO"
    log_json: bool = True
    release: str = "dev"
    heartbeat_url: str | None = None
    """Ping Healthchecks.io раз в минуту из воркера (K33), без адреса — только лог."""


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


class JwtSettings(_Group):
    model_config = SettingsConfigDict(env_prefix="JWT_")

    issuer: str = "sosed"
    access_ttl_seconds: int = Field(default=900, ge=60)
    refresh_ttl_days: int = Field(default=30, ge=1)
    keys_dir: Path | None = None


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
