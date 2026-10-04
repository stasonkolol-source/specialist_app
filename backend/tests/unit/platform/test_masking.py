"""Маскирование ПД и секретов в логах (ARCHITECTURE §13.5, DEVELOPMENT_PLAN 0.4)."""

import json
import logging

import pytest
import structlog

from app.platform.observability.logging import configure_logging
from app.platform.observability.masking import MASK, mask_string, mask_value
from app.platform.observability.sentry import _scrub
from app.platform.settings import AppSettings

pytestmark = pytest.mark.unit

BOT_TOKEN = "8123456789:AAE" + "x" * 32


@pytest.mark.parametrize(
    ("raw", "secret_part"),
    [
        ("звонить на +381 64 123 4567 вечером", "123 4567"),
        ("тел. +7 (999) 123-45-67", "123-45-67"),
        ("local 0641234567 ok", "0641234567"),
        ("tg id 5123456789 joined", "5123456789"),
        (f"token {BOT_TOKEN} leaked", BOT_TOKEN),
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ("jwt eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlX3Bhcnq", "eyJhbGciOiJFZERTQSJ9"),
        ("query_id=AAH&user=%7B%22id%22%3A1%7D&auth_date=1727400000&hash=deadbeef", "deadbeef"),
        ("postgresql+psycopg://app:S3cr3t-pass@127.0.0.1:55442/specialist", "S3cr3t-pass"),
        # ping URL Healthchecks (3.3): httpx пишет адрес запроса в INFO-лог
        (
            'HTTP Request: GET https://hc-ping.com/0f5d7c2e-1b2a-4c3d-9e8f-0123456789ab "200 OK"',
            "0f5d7c2e-1b2a",
        ),
        ("ping https://hc-ping.com/pingKey123/sosed-worker failed", "pingKey123"),
    ],
)
def test_sensitive_fragments_are_masked(raw: str, secret_part: str) -> None:
    masked = mask_string(raw)
    assert secret_part not in masked


@pytest.mark.parametrize(
    "safe",
    [
        "job_published",
        "2026-09-27",
        "2026-09-27T10:15:30.123456Z",
        "0199b5c3-1234-7abc-8def-0123456789ab",
        "цена 5 000 RSD, откликов 3 из 5",
        "retry in 12.5s",
    ],
)
def test_harmless_values_are_untouched(safe: str) -> None:
    assert mask_string(safe) == safe


def test_sensitive_keys_are_masked_entirely() -> None:
    event = {"text": "позвоните мне", "phone": "+381641234567", "init_data": "x", "job_id": "j1"}
    masked = mask_value(None, event)
    assert masked == {"text": MASK, "phone": MASK, "init_data": MASK, "job_id": "j1"}


def test_nested_structures_are_masked() -> None:
    masked = mask_value(None, {"payload": [{"token": "t"}, "call +381641234567"]})
    assert masked == {"payload": [{"token": MASK}, "call [phone]"]}


def test_logger_output_is_masked(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(AppSettings(log_json=True, _env_file=None))
    try:
        structlog.get_logger("test").info(
            "message_relayed", text="мой номер +381641234567", note=f"bot {BOT_TOKEN}"
        )
        line = capsys.readouterr().err.strip().splitlines()[-1]
    finally:
        structlog.reset_defaults()
    record = json.loads(line)
    assert record["event"] == "message_relayed"
    assert record["text"] == MASK
    assert BOT_TOKEN not in record["note"]
    assert "timestamp" in record
    assert record["level"] == "info"


def test_stdlib_logs_go_through_masking(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(AppSettings(log_json=True, _env_file=None))
    try:
        logging.getLogger("aiogram").warning("send to +381641234567 failed")
        err = capsys.readouterr().err
    finally:
        structlog.reset_defaults()
    assert "+381641234567" not in err
    assert "[phone]" in err


def test_ai_sdk_loggers_never_log_request_bodies() -> None:
    # на DEBUG SDK пишут тело запроса — текст пользователя и промпт
    configure_logging(AppSettings(log_level="DEBUG", _env_file=None))
    try:
        assert logging.getLogger("anthropic").getEffectiveLevel() == logging.INFO
        assert logging.getLogger("httpx2").getEffectiveLevel() == logging.INFO
        assert logging.getLogger("aiogram").getEffectiveLevel() == logging.DEBUG
    finally:
        structlog.reset_defaults()
        for name in ("anthropic", "httpx2"):
            logging.getLogger(name).setLevel(logging.NOTSET)
        logging.getLogger().setLevel(logging.WARNING)


def test_sentry_event_hides_secrets_and_client_addresses() -> None:
    # событие Sentry с заголовками запроса: секрет webhook бота, initData, адреса клиента (8.4)
    event = {
        "request": {
            "url": "https://api.example.test/api/v1/auth/telegram",
            "headers": {
                "Authorization": "tma query_id=AAH&user=%7B%7D&auth_date=1727400000&hash=ab12",
                "X-Telegram-Bot-Api-Secret-Token": "webhook-secret-value",
                "CF-Connecting-IP": "93.87.12.34",
                "X-Forwarded-For": "93.87.12.34, 162.158.90.17",
                "X-Request-ID": "req-1",
            },
            "data": {"refresh_token": "r1", "text": "мой номер +381641234567"},
        },
        "extra": {"email": "a@example.test", "webhook_secret": "s"},
    }
    scrubbed = _scrub(event, None)
    dumped = json.dumps(scrubbed, ensure_ascii=False)
    for secret in ("webhook-secret-value", "93.87.12.34", "hash=ab12", "r1", "+381641234567"):
        assert secret not in dumped
    assert "a@example.test" not in dumped
    assert scrubbed["request"]["headers"]["X-Request-ID"] == "req-1"
