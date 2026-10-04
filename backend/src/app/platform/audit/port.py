"""Порт AuditLog (ADR-0020 §4, ARCHITECTURE §7.10): журнал только на добавление.

Запись идёт в транзакцию текущего UoW: действие и запись о нём фиксируются вместе.
Действие — `<область>.<объект>.<что>` (`auth.refresh.reused`, `moderation.case.decided`).
Чтение журнала — `AuditReader` (Admin API `/audit-log`, 2.7b): новые первыми, курсор — id.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.platform.kernel.pagination import Page, PageRequest


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


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditFilter:
    action: str | None = None
    """Действие целиком или его начало до точки: `moderation.case` — все действия с кейсами."""
    actor_id: UUID | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditRecord:
    id: int
    action: str
    actor_kind: ActorKind
    actor_id: UUID | None
    entity_type: str | None
    entity_id: UUID | None
    changes: Mapping[str, object] | None
    ip: str | None
    created_at: datetime


class AuditReader(Protocol):
    async def records(self, query: AuditFilter, page: PageRequest) -> Page[AuditRecord]:
        """Записи по фильтру, новые первыми. InvalidCursorError — курсор битый."""
        ...
