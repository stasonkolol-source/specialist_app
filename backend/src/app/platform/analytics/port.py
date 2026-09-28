"""Порт продуктовой аналитики (DEVELOPMENT_PLAN 1.7).

Событие собирает `events.analytics_event` — там проверка свойств по таксономии: сюда
приходят только события без персональных данных.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

type PropertyValue = str | int | bool
"""Значение свойства: строка из закрытого списка, число (счётчик, id справочника) или флаг."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AnalyticsEvent:
    name: str
    distinct_id: UUID
    """Внутренний UUID пользователя — не Telegram id и не устройство."""
    occurred_at: datetime
    event_id: UUID
    """Идемпотентность: повтор задачи отправляет тот же id, PostHog считает событие один раз."""
    properties: Mapping[str, PropertyValue] = field(default_factory=dict)


class Analytics(Protocol):
    async def capture(self, event: AnalyticsEvent) -> None:
        """Отправить событие. Временная ошибка сервиса — ExternalServiceError (повтор задачи)."""
        ...
