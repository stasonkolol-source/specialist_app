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
отдельное отображение тех же таблиц в своём реестре, без влияния на метаданные модулей.
"""

import re
from datetime import datetime
from typing import Any, ClassVar, Final, override
from uuid import UUID

from sqladmin import BaseView, expose
from sqlalchemy.orm import registry
from starlette.requests import Request
from starlette.responses import Response

from app.platform.config.cache import TTL, ClientConfigCache
from app.platform.config.port import CLIENT_CONFIG_MAX_AGE
from app.platform.db.platform_tables import audit_log, client_config, feature_flags
from app.platform.http.admin import ADMIN, StaffModelView, container_of, staff_id, staff_roles
from app.platform.kernel.clock import Clock
from app.platform.legal.port import LegalDocument, LegalLibrary
from app.platform.settings import AppSettings, TelegramSettings

PROPAGATION: Final = (
    f"Действует без релиза: этот процесс видит правку сразу, остальные — за {TTL.seconds} с"
    " (кэш конфигурации), Mini App — после кэша GET /client-config"
    f" (max-age {CLIENT_CONFIG_MAX_AGE} с), то есть не позже чем через полторы минуты."
)
MIN_VERSIONS: Final = "min_versions"
LEGAL_VERSIONS: Final = "legal_versions"
REQUIRED_LEGAL: Final = (LegalDocument.TERMS, LegalDocument.PRIVACY)
"""Версии, с которыми identity сверяет согласие S02c: без них галочку не поставить."""
_PLATFORM = re.compile(r"[a-z]+")
_VERSION = re.compile(r"\d+(\.\d+){0,2}")


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


class FeatureFlagRecord:
    key: str
    enabled: bool
    value: object | None
    public: bool
    description: str
    updated_at: datetime
    updated_by: UUID | None


class ClientConfigRecord:
    key: str
    value: object
    updated_at: datetime
    updated_by: UUID | None


_platform = registry()
_platform.map_imperatively(AuditRecord, audit_log)
_platform.map_imperatively(FeatureFlagRecord, feature_flags)
_platform.map_imperatively(ClientConfigRecord, client_config)


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


class _ConfigView(StaffModelView):
    """Строка конфигурации: кто и когда менял, сброс снимка конфигурации процесса."""

    roles = ADMIN
    category = "Платформа"
    can_create = can_delete = False
    help_text = PROPAGATION

    @override
    async def on_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        clock: Clock = await container_of(request).get(Clock)
        model.updated_at = clock.now()
        model.updated_by = staff_id(request)

    @override
    async def after_change(self, model: Any, request: Request) -> None:
        (await container_of(request).get(ClientConfigCache)).invalidate()


class FeatureFlagAdmin(_ConfigView, model=FeatureFlagRecord):
    name = "Feature flag"
    name_plural = "Feature flags"
    icon = "fa-solid fa-toggle-on"
    audit_entity = "platform.feature_flag"
    column_list: ClassVar[Any] = [
        feature_flags.c.key,
        feature_flags.c.enabled,
        feature_flags.c.public,
        feature_flags.c.description,
        feature_flags.c.value,
        feature_flags.c.updated_at,
        feature_flags.c.updated_by,
    ]
    column_details_list: ClassVar[Any] = column_list
    column_labels: ClassVar[Any] = {
        feature_flags.c.public: "в client-config",
        feature_flags.c.updated_by: "кто менял",
        feature_flags.c.updated_at: "когда",
    }
    column_searchable_list: ClassVar[Any] = [feature_flags.c.key]
    column_default_sort: ClassVar[Any] = [(feature_flags.c.key, False)]
    form_columns: ClassVar[Any] = [feature_flags.c.enabled]
    help_text = (
        f"{PROPAGATION} Публичные флаги («в client-config») видит Mini App: сегмент «Вещи»"
        " (goods.segment), техработы (platform.maintenance — API отвечает 503). Новые флаги"
        " заводит миграция: их имена знает код."
    )


class ClientConfigAdmin(_ConfigView, model=ClientConfigRecord):
    name = "Значение client-config"
    name_plural = "Client-config"
    icon = "fa-solid fa-sliders"
    audit_entity = "platform.client_config"
    column_list: ClassVar[Any] = [
        client_config.c.key,
        client_config.c.value,
        client_config.c.updated_at,
        client_config.c.updated_by,
    ]
    column_details_list: ClassVar[Any] = column_list
    column_labels: ClassVar[Any] = {
        client_config.c.updated_by: "кто менял",
        client_config.c.updated_at: "когда",
    }
    form_columns: ClassVar[Any] = [client_config.c.value]
    help_text = (
        f"{PROPAGATION} min_versions — минимальная версия клиента по платформе, старше — 426"
        ' «обновите приложение»: {"tma": "1.2.0"}. legal_versions — действующие версии'
        " правил и политики: новая версия просит у всех заново принять документы, и её текст"
        " уже должен лежать в content/legal. Значения из окружения — на странице"
        " «Client-config: итог»."
    )

    @override
    async def check_can_edit(self, request: Request, model: Any) -> bool:
        return model.key in {MIN_VERSIONS, LEGAL_VERSIONS} and await super().check_can_edit(
            request, model
        )

    @override
    async def on_model_change(
        self, data: dict[str, Any], model: Any, is_created: bool, request: Request
    ) -> None:
        value = data.get("value")
        if model.key == MIN_VERSIONS:
            _check_min_versions(value)
        elif model.key == LEGAL_VERSIONS:
            _check_legal_versions(value, await container_of(request).get(LegalLibrary))
        else:
            raise ValueError(f"{model.key}: только для чтения")
        await super().on_model_change(data, model, is_created, request)


def _check_min_versions(value: object) -> None:
    if not isinstance(value, dict) or not all(
        isinstance(platform, str)
        and isinstance(version, str)
        and _PLATFORM.fullmatch(platform)
        and _VERSION.fullmatch(version)
        for platform, version in value.items()
    ):
        raise ValueError(
            'min_versions: объект {"tma": "1.2.0"} — платформа латиницей, версия из цифр'
        )


def _check_legal_versions(value: object, library: LegalLibrary) -> None:
    if not isinstance(value, dict):
        raise ValueError('legal_versions: объект {"terms": "…", "privacy": "…"}')
    for document in REQUIRED_LEGAL:
        if document.value not in value:
            raise ValueError(f"legal_versions: нужна версия {document.value}")
    for key, version in value.items():
        if key not in LegalDocument.__members__.values():
            raise ValueError(f"legal_versions: неизвестный документ {key}")
        # иначе GET /client-config не отдаст текст, а согласие с версией без текста — пустое
        if not isinstance(version, str) or library.edition(LegalDocument(key), version) is None:
            raise ValueError(f"legal_versions: текста {key} версии {version} нет в content/legal")


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
