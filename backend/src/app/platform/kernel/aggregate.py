"""Основа агрегатов (ADR-0020 §2): события, версия для optimistic locking, история статусов."""

from copy import deepcopy
from dataclasses import dataclass, field, fields
from datetime import datetime

from app.platform.kernel.errors import StaleVersionError
from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import UserId


@dataclass(eq=False, kw_only=True)
class AggregateRoot:
    """Сущность с идентичностью объекта: eq=False, сравнение состояний — aggregate_state."""

    _events: list[DomainEvent] = field(default_factory=list, init=False, repr=False)

    def _record(self, event: DomainEvent) -> None:
        self._events.append(event)

    def pull_events(self) -> list[DomainEvent]:
        """Забрать накопленные события. Вызывает только UoW при commit."""
        events, self._events = self._events, []
        return events


@dataclass(eq=False, kw_only=True)
class VersionedAggregate(AggregateRoot):
    """Агрегат, который правят несколько участников: версия для If-Match и version_id_col."""

    version: int

    def ensure_version(self, expected: int | None) -> None:
        """Сравнить версию из If-Match. None — клиент версию не передал."""
        if expected is not None and expected != self.version:
            raise StaleVersionError(expected=expected, actual=self.version)

    def mark_persisted(self, *, version: int) -> None:
        """Новая версия после flush. Вызывает только репозиторий."""
        self.version = version


@dataclass(frozen=True, slots=True, kw_only=True)
class StatusChange[S]:
    """Запись истории перехода: репозиторий вставляет её в `<схема>.status_history`."""

    from_: S
    to: S
    actor_id: UserId | None
    reason: str | None
    at: datetime


def aggregate_state(aggregate: AggregateRoot) -> dict[str, object]:
    """Снимок публичного состояния (поля без «_»): UoW ловит по нему забытый save,
    тесты сравнивают агрегаты."""
    return {
        f.name: deepcopy(getattr(aggregate, f.name))
        for f in fields(aggregate)
        if not f.name.startswith("_")
    }
