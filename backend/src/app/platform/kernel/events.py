"""Базовое доменное событие (ADR-0020 §2, §8). Конкретные события —
в `platform/contracts/events/<модуль>.py` (шаг 0.10)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar
from uuid import UUID

from app.platform.kernel.ids import new_id


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """Факт в прошедшем времени. Тип события — `<модуль>.<Имя>`, версия схемы — schema_version."""

    event_type: ClassVar[str] = "platform.DomainEvent"
    schema_version: ClassVar[int] = 1

    occurred_at: datetime
    event_id: UUID = field(default_factory=new_id)
