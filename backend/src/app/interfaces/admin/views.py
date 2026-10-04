"""Журнал аудита в админке (DEVELOPMENT_PLAN 2.7b; ARCHITECTURE §7.10): только чтение, admin.

`platform.audit_log` — таблица Core (пишет порт AuditLog); SQLAdmin нужен ORM-класс, поэтому
здесь — отдельное отображение той же таблицы в своём реестре, без влияния на метаданные модулей.
"""

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy.orm import registry

from app.platform.db.platform_tables import audit_log
from app.platform.http.admin import ADMIN, StaffModelView


class AuditRecord:
    id: int
    actor_id: UUID | None
    actor_kind: str
    action: str
    entity_type: str | None
    entity_id: UUID | None
    changes: dict[str, Any] | None
    ip: str | None
    created_at: datetime


registry().map_imperatively(AuditRecord, audit_log)


class AuditLogAdmin(StaffModelView, model=AuditRecord):
    name = "Запись аудита"
    name_plural = "Журнал аудита"
    icon = "fa-solid fa-clipboard-list"
    roles = ADMIN
    audit_entity = "platform.audit_log"
    can_create = can_edit = can_delete = False
    column_list: ClassVar[Any] = [
        audit_log.c.created_at,
        audit_log.c.action,
        audit_log.c.actor_kind,
        audit_log.c.actor_id,
        audit_log.c.entity_type,
        audit_log.c.entity_id,
    ]
    column_searchable_list: ClassVar[Any] = [audit_log.c.action]
    column_default_sort: ClassVar[Any] = [(audit_log.c.id, True)]
