"""Атрибуция: откуда пришёл пользователь (ARCHITECTURE §7.3 `growth.attributions`, §11.4).

Считается первое касание — код deep link, с которым пользователь зарегистрировался в Mini
App (`startapp`) или в боте (`/start <payload>`). Второе касание его не перезаписывает:
правило держит первичный ключ `user_id` таблицы, поэтому атрибуция — простая запись без
агрегата (ADR-0020 §5).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.modules.growth.domain.deeplinks import LinkType, is_valid_start_param, parse_start_param
from app.platform.contracts.events.identity import EntryPoint


class AttributionSource(StrEnum):
    """Тип ссылки первого касания. Канал или реферала различает код `_r` (`referral_code`)."""

    ORGANIC = "organic"
    """Без кода: пришёл сам (поиск в Telegram, профиль бота, menu button)."""
    JOB = "job"
    SPECIALIST = "specialist"
    CHAT = "chat"
    DEAL = "deal"
    HOME = "home"
    GOODS = "goods"
    """Зарезервированные коды раздела «Вещи» (после MVP)."""
    UNKNOWN = "unknown"
    """Код есть, но не наш: битый, устаревший или партнёрский Telegram `_tgr_`."""


_SOURCE_BY_LINK: Final = {
    LinkType.JOB: AttributionSource.JOB,
    LinkType.SPECIALIST: AttributionSource.SPECIALIST,
    LinkType.CHAT: AttributionSource.CHAT,
    LinkType.DEAL: AttributionSource.DEAL,
    LinkType.HOME: AttributionSource.HOME,
    LinkType.RESERVED: AttributionSource.GOODS,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class FirstTouch:
    source: AttributionSource
    start_param: str | None
    """Сырой код — только в синтаксисе Telegram (до 64 символов `[A-Za-z0-9_-]`)."""
    referral_code: str | None
    """Суффикс `_r<code>`: реферал или код канала (чаты-партнёры, посты)."""
    entry_point: EntryPoint | None

    @classmethod
    def of(cls, start_param: str | None, *, entry_point: EntryPoint | None) -> FirstTouch:
        if not start_param:
            return cls(
                source=AttributionSource.ORGANIC,
                start_param=None,
                referral_code=None,
                entry_point=entry_point,
            )
        link = parse_start_param(start_param)
        return cls(
            source=_SOURCE_BY_LINK[link.type] if link else AttributionSource.UNKNOWN,
            start_param=start_param if is_valid_start_param(start_param) else None,
            referral_code=link.ref if link else None,
            entry_point=entry_point,
        )
