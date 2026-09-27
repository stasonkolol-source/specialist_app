"""Порт времени (ADR-0020 §2): domain не вызывает datetime.now(), время приходит параметром."""

from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Europe/Belgrade")
"""Бизнес-часовой пояс: тихие часы, «сегодня», сроки. Хранение — всегда UTC."""


class Clock(Protocol):
    def now(self) -> datetime:
        """Текущее время, timezone-aware, UTC."""
        ...


class SystemClock:
    """Часы процесса. Единственное место, где читается системное время."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Привести aware-время к UTC; naive-время — ошибка программиста."""
    if value.tzinfo is None:
        raise ValueError("naive datetime: use timezone-aware values")
    return value.astimezone(UTC)
