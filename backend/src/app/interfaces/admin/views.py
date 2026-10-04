"""Разделы платформы в админке (DEVELOPMENT_PLAN 2.7b; ARCHITECTURE §7.10, §8.5; ADR-0020 §1).

- Журнал аудита — только чтение.
- Feature flags и client-config — справочники платформы: ADR-0020 §1 разрешает их правку через
  SQLAdmin. Флаг только переключается (`enabled`): заводит флаг миграция, потому что его имя знает
  код, а параметр (`value`, веса поиска) правится вместе с кодом, который его читает. В
  client-config правятся строки БД (`min_versions`, `legal_versions`) с проверкой формата;
  значения из настроек окружения (APP_MIN_CLIENT_VERSIONS, TELEGRAM_SUPPORT_USERNAME) страница
  «Client-config: итог» показывает только для чтения — они меняются деплоем.
- Каждая правка — в audit_log, строка помнит, кто и когда её менял (`updated_by`, `updated_at`).
  Снимок конфигурации этого процесса сбрасывается сразу, у остальных — за TTL кэша (30 с), у
  клиента — за max-age ответа GET /client-config (60 с): без релиза и перезапуска.

Таблицы platform — Core (пишут порты платформы); SQLAdmin нужен ORM-класс, поэтому здесь —
отдельное отображение тех же таблиц в своём реестре, без влияния на метаданные модулей. Разделы
флагов и client-config с их проверками живут в platform/http/admin_config.py: их же правит
Admin API.
"""

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from sqladmin import BaseView, expose
from sqlalchemy.orm import registry
from starlette.requests import Request
from starlette.responses import Response

from app.platform.config.cache import ClientConfigCache
from app.platform.db.platform_tables import audit_log
from app.platform.http.admin import ADMIN, StaffModelView, container_of, staff_roles
from app.platform.http.admin_config import PROPAGATION, ClientConfigAdmin, FeatureFlagAdmin
from app.platform.settings import AppSettings, TelegramSettings


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


_platform = registry()
_platform.map_imperatively(AuditRecord, audit_log)


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


class ClientConfigOverview(BaseView):
    """Что отдаёт GET /client-config и откуда каждое значение: правка или деплой."""

    name = "Client-config: итог"
    icon = "fa-solid fa-circle-info"
    category = "Платформа"
    identity = "client-config"

    def is_accessible(self, request: Request) -> bool:
        return bool(staff_roles(request) & ADMIN)

    def is_visible(self, request: Request) -> bool:
        return self.is_accessible(request)

    @expose("/client-config", methods=["GET"])
    async def overview(self, request: Request) -> Response:
        container = container_of(request)
        app = await container.get(AppSettings)
        telegram = await container.get(TelegramSettings)
        snapshot = await (await container.get(ClientConfigCache)).get()
        rows = [
            {
                "key": "min_versions",
                "value": {**app.min_client_versions, **snapshot.min_versions},
                "source": "APP_MIN_CLIENT_VERSIONS (окружение), поверх — строка min_versions",
                "edit": "client-config-record",
            },
            {
                "key": "min_versions (окружение)",
                "value": app.min_client_versions,
                "source": "APP_MIN_CLIENT_VERSIONS — меняется деплоем",
                "edit": None,
            },
            {
                "key": "legal_versions",
                "value": dict(snapshot.legal_versions),
                "source": "строка legal_versions",
                "edit": "client-config-record",
            },
            {
                "key": "flags",
                "value": snapshot.public_flags(),
                "source": "публичные feature flags",
                "edit": "feature-flag-record",
            },
            {
                "key": "support_username",
                "value": telegram.support_username,
                "source": "TELEGRAM_SUPPORT_USERNAME — меняется деплоем",
                "edit": None,
            },
        ]
        return await self._admin_ref.templates.TemplateResponse(
            request, "admin/client_config.html", {"rows": rows, "propagation": PROPAGATION}
        )


VIEWS = (FeatureFlagAdmin, ClientConfigAdmin, ClientConfigOverview, AuditLogAdmin)
