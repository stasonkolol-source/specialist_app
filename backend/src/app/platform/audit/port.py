"""Порт AuditLog (ADR-0020 §4, ARCHITECTURE §7.10): журнал только на добавление.

Запись идёт в транзакцию текущего UoW: действие и запись о нём фиксируются вместе.
Действие — `<область>.<объект>.<что>` (`auth.refresh.reused`, `moderation.case.decided`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class ActorKind(StrEnum):
    USER = "user"
    STAFF = "staff"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditEntry:
    action: str
    actor_kind: ActorKind
    actor_id: UUID | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None
    changes: Mapping[str, object] | None = None
    ip: str | None = None


class AuditLog(Protocol):
    async def record(self, entry: AuditEntry) -> None:
        """Добавить запись в текущую транзакцию; без активного UoW — ошибка программиста."""
        ...
