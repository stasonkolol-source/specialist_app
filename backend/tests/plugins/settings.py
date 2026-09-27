"""Настройки процесса для тестов с контейнерами (DI, воркер, HTTP)."""

import pytest

from app.platform.settings import GROUPS, Settings, env_names
from tests.plugins.containers import PostgresInfo


@pytest.fixture
def settings(postgres: PostgresInfo, valkey_url: str, monkeypatch: pytest.MonkeyPatch) -> Settings:
    for group in GROUPS:
        for name in env_names(group):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DB_DSN", postgres.dsn("app"))
    monkeypatch.setenv("VALKEY_URL", valkey_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "8123456789:AAE" + "x" * 32)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "sosed_test_bot")
    monkeypatch.setenv("APP_LOG_JSON", "true")
    return Settings(env_file=None)
