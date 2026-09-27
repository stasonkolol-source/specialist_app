"""Настройки процессов (ADR-0020 §10, DEVELOPMENT_PLAN 0.4)."""

from pathlib import Path

import pytest

from app.platform.settings import (
    GROUPS,
    DbSettings,
    Environment,
    Settings,
    SettingsError,
    env_names,
)

pytestmark = pytest.mark.unit

BACKEND = Path(__file__).resolve().parents[3]
REQUIRED = {
    "DB_DSN": "postgresql+psycopg://app:pw@127.0.0.1:55442/specialist",
    "VALKEY_URL": "redis://127.0.0.1:56379/0",
    "TELEGRAM_BOT_TOKEN": "8123456789:AAE" + "x" * 32,
    "TELEGRAM_BOT_USERNAME": "sosed_dev_bot",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for group in GROUPS:
        for name in env_names(group):
            monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def test_missing_required_settings_give_a_clear_error(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(SettingsError) as exc:
        Settings(env_file=None)
    message = str(exc.value)
    for name in REQUIRED:
        assert name in message


def test_invalid_value_is_reported_by_name(clean_env: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.setenv("DB_POOL_SIZE", "0")
    with pytest.raises(SettingsError, match="DB_POOL_SIZE"):
        Settings(env_file=None)


def test_settings_load_from_environment(clean_env: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.setenv("APP_ENV", "stage")
    settings = Settings(env_file=None)
    assert settings.app.env is Environment.STAGE
    assert settings.telegram.bot_username == "sosed_dev_bot"
    assert settings.db.dsn.get_secret_value() == REQUIRED["DB_DSN"]
    # секреты не видны в repr
    assert "AAE" not in repr(settings.telegram)
    assert "pw@" not in repr(settings.db)


def test_empty_values_count_as_unset(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("\n".join(f"{k}={v}" for k, v in REQUIRED.items()) + "\nDB_POOL_SIZE=\n")
    assert DbSettings(_env_file=env).pool_size == 10


def test_every_setting_is_listed_in_env_example() -> None:
    listed = set(_read_env(BACKEND / ".env.example"))
    expected = {name for group in GROUPS for name in env_names(group)}
    assert expected - listed == set(), "добавьте новые настройки в backend/.env.example"
    assert listed - expected == set(), "в backend/.env.example лишние имена"


@pytest.mark.parametrize("name", [".env.example", ".env"])
def test_env_values_have_no_quotes(name: str) -> None:
    path = BACKEND / name
    if not path.exists():
        pytest.skip(f"{name} отсутствует (CI)")
    bad = [key for key, value in _read_env(path).items() if any(c in value for c in "\"'")]
    assert bad == [], f"кавычки в значениях {bad}: Docker --env-file их не снимает"
