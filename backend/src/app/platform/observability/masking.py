"""Маскирование персональных данных и секретов в логах и событиях Sentry.

ARCHITECTURE §13.5: телефоны, initData, токены и тексты сообщений в логи не попадают.
Маскирование — страховка, а не разрешение: код не должен логировать ПД сам (ADR-0020 §10).
"""

import re
from collections.abc import Mapping
from typing import Any

MASK = "[masked]"

# Поля, значение которых скрывается целиком, по имени (без учёта регистра).
SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "bot_token",
        "api_key",
        "x-api-key",
        "x_api_key",
        "init_data",
        "initdata",
        "init_data_raw",
        "phone",
        "phone_number",
        "text",
        "message_text",
        "caption",
        "dsn",
        "cookie",
        "set-cookie",
        # секрет webhook бота и адреса клиента в заголовках событий Sentry (8.4)
        "x-telegram-bot-api-secret-token",
        "webhook_secret",
        "hash_key",
        "private_key",
        "client_secret",
        "cf-connecting-ip",
        "x-forwarded-for",
        "x-real-ip",
        "email",
    }
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Токен бота Telegram: 123456789:AA… (35 символов после двоеточия)
    (re.compile(r"\b\d{5,16}:[A-Za-z0-9_-]{35}\b"), "[bot-token]"),
    # JWT: три base64url-части через точку
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), "[jwt]"),
    # Authorization: Bearer …
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [masked]"),
    # initData — строка запроса с hash= и user= / auth_date=
    (
        re.compile(
            r"(?:query_id|user|auth_date|signature|hash|chat_instance)=[^&\s]+(?:&[^&\s]+)*"
        ),
        "[init-data]",
    ),
    # Телефоны в международном формате: +381 64 123 4567, +7 (999) 123-45-67
    (re.compile(r"(?<![\w+])\+\d[\d\s().-]{6,}\d(?![\w])"), "[phone]"),
    # Длинные цифровые серии отдельным словом: местные номера 0641234567, Telegram ID.
    # Даты, время и UUID не затрагиваются: цифры в них разделены или стоят рядом с буквами.
    (re.compile(r"(?<![\w.:-])\d{9,15}(?![\w.:-])"), "[digits]"),
    # Пароль в DSN: scheme://user:password@host
    (re.compile(r"(\w+://[^:/\s]+):[^@\s]+@"), r"\1:[masked]@"),
    # Ping URL Healthchecks.io (K33): uuid или ключ проекта в пути — по нему любой отметит
    # проверку. httpx пишет адрес запроса в INFO-лог, Sentry — в breadcrumbs
    (re.compile(r"(https?://(?:hc-ping\.com|healthchecks\.io/ping))/[^\s\"'<>]+"), r"\1/[masked]"),
)


def mask_string(value: str) -> str:
    """Заменить в строке всё, что похоже на токены, initData, телефоны и пароли."""
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def mask_value(key: str | None, value: Any) -> Any:
    """Замаскировать значение с учётом имени поля; словари и списки — рекурсивно."""
    if key is not None and key.lower() in SENSITIVE_KEYS and value not in (None, ""):
        return MASK
    if isinstance(value, str):
        return mask_string(value)
    if isinstance(value, Mapping):
        return {k: mask_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(mask_value(None, v) for v in value)
    return value


def mask_event_dict(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Процессор structlog: маскирует все поля события, включая текст события."""
    return {
        key: mask_value(key if key != "event" else None, value) for key, value in event_dict.items()
    }
