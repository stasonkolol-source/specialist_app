"""Настройки процессов (ADR-0020 §10, DEVELOPMENT_PLAN 0.4)."""

import secrets
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.platform.settings import (
    GROUPS,
    DbSettings,
    Environment,
    Settings,
    SettingsError,
    UpdatesMode,
    describe,
    env_names,
    key_bytes,
    webhook_base_url,
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
    clean_env.setenv("APP_HASH_KEY", "test-hash-key")
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


def test_explicitly_empty_app_env_stops_the_process(clean_env: pytest.MonkeyPatch) -> None:
    # пустое значение стало бы dev — и заглушками AI, которые пропускают всё
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.setenv("APP_ENV", "")
    with pytest.raises(SettingsError, match="APP_ENV"):
        Settings(env_file=None)


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


def test_production_refuses_legal_placeholders(clean_env: pytest.MonkeyPatch) -> None:
    """Оператор и почта попадают в политику конфиденциальности (1.5a): заглушка — не на проде."""
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.setenv("APP_ENV", "stage")
    clean_env.setenv("APP_HASH_KEY", "test-hash-key")
    assert Settings(env_file=None).legal.todo_fields() == [
        "LEGAL_OPERATOR_NAME",
        "LEGAL_CONTACT_EMAIL",
    ]
    clean_env.setenv("APP_ENV", "production")
    clean_env.setenv("LEGAL_OPERATOR_NAME", "Оператор")
    with pytest.raises(SettingsError, match="LEGAL_CONTACT_EMAIL"):
        Settings(env_file=None)
    clean_env.setenv("LEGAL_CONTACT_EMAIL", "help@example.test")
    assert Settings(env_file=None).legal.todo_fields() == []


def test_stage_and_production_need_the_hash_key(clean_env: pytest.MonkeyPatch) -> None:
    """Хэши удалённых аккаунтов (2.12): без постоянного ключа антифрод «забыл» бы их."""
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    assert Settings(env_file=None).app.hash_key is None  # dev — ключ разработки
    clean_env.setenv("APP_ENV", "stage")
    with pytest.raises(SettingsError, match="APP_HASH_KEY"):
        Settings(env_file=None)


def test_stage_and_production_with_admin_need_the_totp_key(clean_env: pytest.MonkeyPatch) -> None:
    """Секреты TOTP персонала (8.4): с включённой админкой без ключа шифрования не стартуем."""
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.setenv("APP_HASH_KEY", "test-hash-key")
    clean_env.setenv("APP_ADMIN_SESSION_KEY", "test-session-key")
    assert Settings(env_file=None).app.totp_key is None  # dev — ключ разработки
    clean_env.setenv("APP_ENV", "stage")
    with pytest.raises(SettingsError, match="APP_TOTP_KEY"):
        Settings(env_file=None)
    clean_env.delenv("APP_ADMIN_SESSION_KEY")
    assert Settings(env_file=None).app.totp_key is None  # админка выключена — входа нет
    clean_env.setenv("APP_ADMIN_SESSION_KEY", "test-session-key")
    clean_env.setenv("APP_TOTP_KEY", secrets.token_hex(32))
    assert Settings(env_file=None).app.totp_key is not None


@pytest.mark.parametrize("name", ["APP_TOTP_KEY", "APP_TOTP_KEY_PREVIOUS"])
@pytest.mark.parametrize("value", ["short-password", "ab" * 31, "z" * 64])
def test_totp_key_must_be_32_bytes(clean_env: pytest.MonkeyPatch, name: str, value: str) -> None:
    for required, given in REQUIRED.items():
        clean_env.setenv(required, given)
    clean_env.setenv(name, value)
    with pytest.raises(SettingsError, match=name):
        Settings(env_file=None)


def test_totp_key_is_hex_or_base64url() -> None:
    """`make gen-secret` даёт hex, `secrets.token_urlsafe(32)` — base64url: оба — 32 байта."""
    raw = secrets.token_bytes(32)
    assert key_bytes(SecretStr(raw.hex())) == raw
    assert key_bytes(SecretStr(secrets.token_urlsafe(32))) != raw
    assert len(key_bytes(SecretStr(secrets.token_urlsafe(32)))) == 32


def test_metrics_port_is_off_by_default(clean_env: pytest.MonkeyPatch) -> None:
    """Экспорт метрик (3.3) — только с METRICS_PORT: dev и тесты без него."""
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    assert Settings(env_file=None).metrics.port is None
    clean_env.setenv("METRICS_PORT", "9091")
    clean_env.setenv("METRICS_HOST", "0.0.0.0")  # noqa: S104 — так в контейнере
    metrics = Settings(env_file=None).metrics
    assert (metrics.host, metrics.port) == ("0.0.0.0", 9091)  # noqa: S104


def test_heartbeat_url_is_a_secret_and_keeps_the_old_name(clean_env: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.delenv("APP_HEARTBEAT_URL", raising=False)
    assert Settings(env_file=None).healthchecks.worker_ping_url is None
    clean_env.setenv("APP_HEARTBEAT_URL", "https://hc-ping.com/old")  # имя до 3.3
    url = Settings(env_file=None).healthchecks.worker_ping_url
    assert url is not None
    assert url.get_secret_value() == "https://hc-ping.com/old"
    clean_env.setenv("HEALTHCHECKS_WORKER_PING_URL", "https://hc-ping.com/new")
    settings = Settings(env_file=None)
    assert settings.healthchecks.worker_ping_url is not None
    assert settings.healthchecks.worker_ping_url.get_secret_value() == "https://hc-ping.com/new"
    assert "hc-ping" not in repr(settings.healthchecks)


def test_release_falls_back_to_the_kamal_image_version(clean_env: pytest.MonkeyPatch) -> None:
    """Релиз Sentry (3.3): APP_RELEASE, иначе KAMAL_VERSION из контейнера, иначе dev."""
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.delenv("KAMAL_VERSION", raising=False)
    assert Settings(env_file=None).app.release == "dev"
    clean_env.setenv("KAMAL_VERSION", "3f2a9c1")
    assert Settings(env_file=None).app.release == "3f2a9c1"
    clean_env.setenv("APP_RELEASE", "v42")
    assert Settings(env_file=None).app.release == "v42"


def test_webhook_mode_needs_a_strong_secret_and_https(clean_env: pytest.MonkeyPatch) -> None:
    """Без секрета aiogram принял бы любой POST, на http:// Telegram не шлёт апдейты (0.25e)."""
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    assert Settings(env_file=None).telegram.updates is UpdatesMode.POLLING
    clean_env.setenv("TELEGRAM_UPDATES", "webhook")
    with pytest.raises(SettingsError, match="не задан TELEGRAM_WEBHOOK_SECRET"):
        Settings(env_file=None)
    for weak in ("short-secret", "x" * 31, "x" * 257, "x" * 40 + "!"):
        clean_env.setenv("TELEGRAM_WEBHOOK_SECRET", weak)
        with pytest.raises(SettingsError, match="32–256 символов") as exc:
            Settings(env_file=None)
        assert weak not in str(exc.value)  # значение секрета в ошибку не попадает
    clean_env.setenv("TELEGRAM_WEBHOOK_SECRET", "x" * 64)
    with pytest.raises(SettingsError, match="APP_API_PUBLIC_URL"):
        Settings(env_file=None)  # по умолчанию http://127.0.0.1:8000
    clean_env.setenv("APP_API_PUBLIC_URL", "https://stage-api.example.test")
    assert Settings(env_file=None).telegram.updates is UpdatesMode.WEBHOOK


def test_polling_ignores_the_webhook_secret_format(clean_env: pytest.MonkeyPatch) -> None:
    """В dev секрет не нужен: случайное значение в backend/.env не должно ронять стенд."""
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.setenv("TELEGRAM_WEBHOOK_SECRET", "dev")
    assert Settings(env_file=None).telegram.updates is UpdatesMode.POLLING


def test_unknown_updates_mode_is_reported(clean_env: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.setenv("TELEGRAM_UPDATES", "push")
    with pytest.raises(SettingsError, match="TELEGRAM_UPDATES"):
        Settings(env_file=None)


def test_webhook_goes_to_its_own_bot_host(clean_env: pytest.MonkeyPatch) -> None:
    """kamal-proxy не отдаёт один хост с TLS двум ролям: у бота свой (stage-bot.<домен>)."""
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.setenv("TELEGRAM_UPDATES", "webhook")
    clean_env.setenv("TELEGRAM_WEBHOOK_SECRET", "x" * 64)
    # API на http (по умолчанию), бот — на своём https-хосте: так можно
    clean_env.setenv("TELEGRAM_WEBHOOK_BASE_URL", "https://stage-bot.example.test")
    settings = Settings(env_file=None)
    assert webhook_base_url(settings.app, settings.telegram) == "https://stage-bot.example.test"
    for bad, message in (
        ("http://stage-bot.example.test", "TELEGRAM_WEBHOOK_BASE_URL: webhook Telegram принимает"),
        ("https://", "TELEGRAM_WEBHOOK_BASE_URL: webhook Telegram принимает"),
        ("https://stage-bot.example.test/hook", "TELEGRAM_WEBHOOK_BASE_URL: нужны только схема"),
        ("https://stage-bot.example.test?x=1", "TELEGRAM_WEBHOOK_BASE_URL: нужны только схема"),
    ):
        clean_env.setenv("TELEGRAM_WEBHOOK_BASE_URL", bad)
        with pytest.raises(SettingsError, match=message):
            Settings(env_file=None)
    # без своего хоста — адрес API, и проверяется уже он
    clean_env.delenv("TELEGRAM_WEBHOOK_BASE_URL")
    clean_env.setenv("APP_API_PUBLIC_URL", "https://stage-api.example.test/api")
    with pytest.raises(SettingsError, match="APP_API_PUBLIC_URL: нужны только схема"):
        Settings(env_file=None)
    clean_env.setenv("APP_API_PUBLIC_URL", "https://stage-api.example.test/")
    settings = Settings(env_file=None)
    assert webhook_base_url(settings.app, settings.telegram) == "https://stage-api.example.test/"


def test_fake_telegram_sender_is_refused_in_production(clean_env: pytest.MonkeyPatch) -> None:
    """Фейк нагрузочного прогона (8.3) глотает уведомления: на stage можно, на проде — нет."""
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.setenv("APP_HASH_KEY", "test-hash-key")
    clean_env.setenv("TELEGRAM_FAKE_SENDER", "true")
    clean_env.setenv("APP_ENV", "stage")
    assert Settings(env_file=None).telegram.fake_sender is True
    clean_env.setenv("APP_ENV", "production")
    clean_env.setenv("LEGAL_OPERATOR_NAME", "Оператор")
    clean_env.setenv("LEGAL_CONTACT_EMAIL", "help@example.test")
    with pytest.raises(SettingsError, match="TELEGRAM_FAKE_SENDER"):
        Settings(env_file=None)
    clean_env.setenv("TELEGRAM_FAKE_SENDER", "false")
    assert Settings(env_file=None).telegram.fake_sender is False


def test_describe_shows_which_processors_are_on_without_secrets(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """Лог старта — по нему на воротах 3.4 и 8.4 политику сверяют с включёнными обработчиками."""
    for name, value in REQUIRED.items():
        clean_env.setenv(name, value)
    clean_env.delenv("APP_HEARTBEAT_URL", raising=False)  # прежнее имя ping URL (до 3.3)
    off = describe(Settings(env_file=None))
    processors = ("sentry", "heartbeat", "ai_moderation", "ai_classifier", "posthog")
    assert {key: off[key] for key in processors} == dict.fromkeys(processors, False)
    secrets = {
        "SENTRY_DSN": "https://key@o1.ingest.de.sentry.io/2",
        "HEALTHCHECKS_WORKER_PING_URL": "https://hc-ping.com/check-uuid",
        "AI_OPENAI_API_KEY": "sk-openai-secret",
        "AI_ANTHROPIC_API_KEY": "sk-ant-secret",
        "ANALYTICS_POSTHOG_API_KEY": "phc_posthog_secret",
    }
    for name, value in secrets.items():
        clean_env.setenv(name, value)
    on = describe(Settings(env_file=None))
    assert {key: on[key] for key in processors} == dict.fromkeys(processors, True)
    for value in (*secrets.values(), REQUIRED["TELEGRAM_BOT_TOKEN"], REQUIRED["DB_DSN"]):
        assert value not in repr(on)
