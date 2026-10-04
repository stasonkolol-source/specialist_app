"""Feature flags и client-config — справочники платформы (DEVELOPMENT_PLAN 2.7b; ADR-0020 §1).

Разделы SQLAdmin и их проверки — здесь, в platform: их берут и админка (interfaces/admin/views.py),
и Admin API (`/feature-flags`, `/client-config`, interfaces/http/admin_api.py) через
`apply_change` — одни правила, аудит и сброс снимка на оба входа.

- Флаг только переключается (`enabled`): заводит флаг миграция, потому что его имя знает код, а
  параметр (`value`, веса поиска) правится вместе с кодом, который его читает.
- В client-config правятся строки БД (`min_versions`, `legal_versions`) с проверкой формата;
  значения из окружения (APP_MIN_CLIENT_VERSIONS, TELEGRAM_SUPPORT_USERNAME) меняются деплоем.
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

from sqlalchemy.orm import registry
from starlette.requests import Request

from app.platform.config.cache import TTL, ClientConfigCache
from app.platform.config.port import CLIENT_CONFIG_MAX_AGE
from app.platform.db.platform_tables import client_config, feature_flags
from app.platform.http.admin import ADMIN, StaffModelView, container_of, staff_id
from app.platform.kernel.clock import Clock
from app.platform.legal.port import LegalDocument, LegalLibrary

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


_config = registry()
_config.map_imperatively(FeatureFlagRecord, feature_flags)
_config.map_imperatively(ClientConfigRecord, client_config)


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
            check_min_versions(value)
        elif model.key == LEGAL_VERSIONS:
            check_legal_versions(value, await container_of(request).get(LegalLibrary))
        else:
            raise ValueError(f"{model.key}: только для чтения")
        await super().on_model_change(data, model, is_created, request)


def check_min_versions(value: object) -> None:
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


def check_legal_versions(value: object, library: LegalLibrary) -> None:
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


EDITABLE_CONFIG: Final = frozenset({MIN_VERSIONS, LEGAL_VERSIONS})
"""Строки client-config, которые правит админка; остальные — только чтение."""
