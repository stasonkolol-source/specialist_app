"""Настройки процесса для тестов: с контейнерами (DI, воркер) и без них (HTTP-каркас)."""

import pytest

from app.platform.security.jwt import SigningKey
from app.platform.settings import GROUPS, Settings, env_names
from tests.plugins.containers import PostgresInfo

UNREACHABLE = "127.0.0.1:1"
"""Адрес, где никто не слушает: так проверяем, что код не ходит в БД и Valkey."""


def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for group in GROUPS:
        for name in env_names(group):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "8123456789:AAE" + "x" * 32)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "sosed_test_bot")
    monkeypatch.setenv("APP_LOG_JSON", "true")
    monkeypatch.setenv("JWT_KEYS", SigningKey.generate("test").dump())


@pytest.fixture
def settings(postgres: PostgresInfo, valkey_url: str, monkeypatch: pytest.MonkeyPatch) -> Settings:
    _clean(monkeypatch)
    monkeypatch.setenv("DB_DSN", postgres.dsn("app"))
    monkeypatch.setenv("VALKEY_URL", valkey_url)
    return Settings(env_file=None)


@pytest.fixture
def storage_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Настройки с S3 без хранилища: файлы в ответах (фото профиля, работы портфолио) — ссылками
    на адрес CDN, которые строятся без запросов к S3. Ходить в хранилище такие тесты не могут:
    адреса не существуют."""
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://storage.test")
    monkeypatch.setenv("S3_REGION", "garage")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("S3_PUBLIC_BASE_URL", "https://cdn.test")
    return Settings(env_file=None)


@pytest.fixture
def offline_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    _clean(monkeypatch)
    monkeypatch.setenv("DB_DSN", f"postgresql+psycopg://app:pw@{UNREACHABLE}/specialist")
    monkeypatch.setenv("VALKEY_URL", f"redis://{UNREACHABLE}/0")
    monkeypatch.setenv("APP_API_PUBLIC_URL", "https://api.example.test")
    monkeypatch.setenv("APP_MIN_CLIENT_VERSIONS", '{"tma": "1.2.0"}')
    return Settings(env_file=None)
