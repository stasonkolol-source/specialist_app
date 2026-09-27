"""Контракт модуля identity для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из identity только этот файл.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.modules.identity.errors import AccountDeletedError as AccountDeletedError
from app.modules.identity.errors import UserNotFoundError as UserNotFoundError
from app.platform.kernel.ids import UserId
from app.platform.kernel.localized import Locale


class Action(StrEnum):
    """Действие, которое может запретить санкция (identity.restrictions)."""

    LOGIN = "login"
    POST = "post"
    RESPOND = "respond"
    MESSAGE = "message"


@dataclass(frozen=True, slots=True, kw_only=True)
class UserSummary:
    id: UserId
    display_name: str
    ui_locale: Locale
    trust_level: int
    phone_verified: bool
    is_deleted: bool
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class TelegramUserView:
    """Пользователь, которого бот узнал по Telegram id (или только что создал /start)."""

    id: UserId
    display_name: str
    ui_locale: Locale
    trust_level: int


class IdentityApi(Protocol):
    async def get_user(self, user_id: UserId) -> UserSummary | None: ...

    async def by_telegram(self, telegram_id: int) -> TelegramUserView | None:
        """Активный пользователь по Telegram id (бот). Telegram id наружу не отдаём."""
        ...

    async def ensure_allowed(self, user_id: UserId, action: Action) -> None:
        """RestrictedError (403 `restricted`), если действие запрещено действующей санкцией."""
        ...
