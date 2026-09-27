"""Проверка initData Mini App (ADR-0009, research/02 §3.2–3.3).

- secret = HMAC_SHA256(key="WebAppData", msg=bot_token); `hash` = hex(HMAC_SHA256(secret,
  data_check_string)), где data_check_string — все поля, кроме `hash`, по алфавиту через
  `\n` (поле `signature` входит). Сравнение — в постоянное время.
- `auth_date` не старше часа, из будущего — не больше 60 с (расхождение часов).
- initData — bearer-секрет: не логируем, в ошибки не кладём. Полям `initDataUnsafe` на
  клиенте не доверяем: всё берём только отсюда, после проверки подписи.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

from pydantic import SecretStr

from app.platform.kernel.clock import Clock
from app.platform.security.errors import InitDataExpiredError, InvalidInitDataError

MAX_AGE = timedelta(hours=1)
CLOCK_SKEW = timedelta(seconds=60)
MAX_LENGTH = 8192
"""Реальный initData — 0,5–1,5 КБ; длиннее — мусор, не тратим на него HMAC и парсинг."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TelegramUser:
    id: int
    first_name: str
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    is_premium: bool = False
    allows_write_to_pm: bool = False
    photo_url: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class InitData:
    user: TelegramUser
    auth_date: datetime
    query_id: str | None = None
    start_param: str | None = None
    chat_type: str | None = None
    chat_instance: str | None = None


def webapp_secret(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()


def data_check_string(fields: dict[str, str]) -> str:
    return "\n".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "hash")


def sign(fields: dict[str, str], bot_token: str) -> str:
    """hash для набора полей — для тестов и `cli dev-initdata` (шаг 0.22)."""
    secret = webapp_secret(bot_token)
    return hmac.new(secret, data_check_string(fields).encode(), hashlib.sha256).hexdigest()


class InitDataVerifier:
    """Проверяет initData одного бота: токен бота — из TelegramSettings окружения."""

    def __init__(self, bot_token: SecretStr, clock: Clock, *, max_age: timedelta = MAX_AGE) -> None:
        self._secret = webapp_secret(bot_token.get_secret_value())
        self._clock = clock
        self._max_age = max_age

    def verify(self, raw: str) -> InitData:
        fields = _parse(raw)
        received = fields.get("hash", "")
        expected = hmac.new(
            self._secret, data_check_string(fields).encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, received.lower()):
            raise InvalidInitDataError
        auth_date = _auth_date(fields.get("auth_date"))
        now = self._clock.now()
        if auth_date - now > CLOCK_SKEW:
            raise InvalidInitDataError
        if now - auth_date > self._max_age:
            raise InitDataExpiredError
        return InitData(
            user=_user(fields.get("user")),
            auth_date=auth_date,
            query_id=fields.get("query_id"),
            start_param=fields.get("start_param"),
            chat_type=fields.get("chat_type"),
            chat_instance=fields.get("chat_instance"),
        )


def _parse(raw: str) -> dict[str, str]:
    if not raw or len(raw) > MAX_LENGTH:
        raise InvalidInitDataError
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise InvalidInitDataError from exc
    fields = dict(pairs)
    if len(fields) != len(pairs) or "hash" not in fields:
        raise InvalidInitDataError  # повтор ключа — подмена, без hash — не подписано
    return fields


def _auth_date(raw: str | None) -> datetime:
    if raw is None or not raw.isdigit():
        raise InvalidInitDataError
    return datetime.fromtimestamp(int(raw), tz=UTC)


def _user(raw: str | None) -> TelegramUser:
    if raw is None:
        raise InvalidInitDataError  # без user (inline mode) войти нельзя
    try:
        data: Any = json.loads(raw)
    except ValueError as exc:
        raise InvalidInitDataError from exc
    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        raise InvalidInitDataError
    if not isinstance(data.get("first_name"), str):
        raise InvalidInitDataError
    return TelegramUser(
        id=data["id"],
        first_name=data["first_name"],
        last_name=_opt_str(data.get("last_name")),
        username=_opt_str(data.get("username")),
        language_code=_opt_str(data.get("language_code")),
        is_premium=data.get("is_premium") is True,
        allows_write_to_pm=data.get("allows_write_to_pm") is True,
        photo_url=_opt_str(data.get("photo_url")),
    )


def _opt_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
