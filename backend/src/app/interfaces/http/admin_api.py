"""Admin API `/admin/api/v1` (DEVELOPMENT_PLAN 2.7b; ARCHITECTURE §8.5, §13.2; ADR-0009, ADR-0020).

JSON для персонала рядом с SQLAdmin в процессе web: кейсы, жалобы и контент-правила
(moderation), карточка пользователя и санкции (identity), справочники (catalog, geo), рассылки
(notifications); журнал аудита, feature flags и client-config — здесь. Решения — те же use cases,
что у SQLAdmin и `cli`, правка справочников — те же разделы SQLAdmin через `apply_change`;
роутеры — `modules/<m>/admin/router.py`, их собирает композиционный корень.

- Отдельное приложение FastAPI, смонтированное раньше SQLAdmin (иначе путь поглотил бы `/admin`):
  свои обработчики ошибок — тот же problem+json (ADR-0020 §9) — и своя схема:
  backend/admin-openapi.json (`cli openapi`). В публичную openapi.json и api-client Mini App
  операции персонала не попадают: клиенту они не нужны, а их перечень в открытой схеме — лишняя
  разведка для атакующего. Swagger и /openapi.json самого API не отдаются.
- Вход — cookie `sosed_admin` со страницы /admin/login (SessionMiddleware с тем же ключом, сроком
  и флагами, что у SQLAdmin; API cookie только читает). Сотрудник перечитывается на каждый запрос
  (StaffAuth.member): нет роли или вход удалён — 401 `not_authenticated`. Роль операции, CSRF и
  лимит — platform/http/staff.py.
- На stage и проде без APP_ADMIN_SESSION_KEY не монтируется, как и SQLAdmin.
- Ответы не кэшируются (`Cache-Control: no-store` — в них ПД) и запрещены к исполнению (CSP API).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Final
from uuid import UUID

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.interfaces.http.errors import (
    INTERNAL_ERROR,
    Problems,
    install_error_handlers,
    locale_of,
    trace_id_of,
)
from app.interfaces.http.openapi import PROBLEM_RESPONSES, install_openapi
from app.interfaces.http.operation_ids import admin_operation_id
from app.interfaces.http.security_headers import API_CSP
from app.modules.identity.api import StaffAuth
from app.platform.audit.port import AuditFilter, AuditReader, AuditRecord
from app.platform.http.admin import (
    ADMIN,
    AdminRows,
    apply_change,
    as_row,
    container_of,
    table_of,
)
from app.platform.http.admin_config import EDITABLE_CONFIG, ClientConfigAdmin, FeatureFlagAdmin
from app.platform.http.pagination import PageOut, PageParams
from app.platform.http.staff import (
    PUBLISHED,
    SESSION_COOKIE,
    SESSION_KEY,
    SESSION_MAX_AGE,
    csrf_guard,
    session_secret,
    staff_only,
    staff_rate_limit,
)
from app.platform.i18n.translator import Translator
from app.platform.kernel.errors import NotAuthenticatedError, NotFoundError
from app.platform.kernel.ids import UserId
from app.platform.observability.logging import bind_context
from app.platform.settings import Settings

log = structlog.get_logger(__name__)

ADMIN_API_PREFIX: Final = "/admin/api/v1"
ADMIN_API_TITLE: Final = "Соседи Admin API"


def mount_admin_api(
    app: FastAPI,
    settings: Settings,
    routers: Sequence[APIRouter],
    *,
    translator: Translator | None = None,
) -> FastAPI | None:
    """Admin API на `/admin/api/v1` — до `mount_admin`; None — выключен (как SQLAdmin)."""
    secret = session_secret(settings.app)
    if secret is None:
        log.warning("admin_api_disabled", reason="APP_ADMIN_SESSION_KEY is not set")
        return None
    api = _admin_app(routers)
    problems = Problems(
        base_url=settings.app.api_public_url, translator=translator or Translator.load()
    )
    install_error_handlers(api, problems)

    async def internal_error(request: Request, _exc: Exception) -> Response:
        # у вложенного приложения свой ServerErrorMiddleware: без обработчика он ответил бы
        # текстом; исключение он всё равно пробрасывает — его пишет RequestContextMiddleware
        return problems.response(
            500, INTERNAL_ERROR, trace_id=trace_id_of(request), locale=locale_of(request)
        )

    api.add_exception_handler(Exception, internal_error)
    api.add_middleware(_PrivateJson)
    api.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie=SESSION_COOKIE,
        max_age=SESSION_MAX_AGE,
        same_site="strict",
        https_only=settings.app.env in PUBLISHED,
    )
    app.mount(ADMIN_API_PREFIX, api)
    return api


def admin_openapi_spec(routers: Sequence[APIRouter]) -> dict[str, Any]:
    """Схема Admin API без контейнера и настроек: `cli openapi` пишет её в admin-openapi.json."""
    return _admin_app(routers).openapi()


def _admin_app(routers: Sequence[APIRouter]) -> FastAPI:
    api = FastAPI(
        title=ADMIN_API_TITLE,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        generate_unique_id_function=admin_operation_id,
    )
    install_openapi(api, title=ADMIN_API_TITLE, servers=[{"url": ADMIN_API_PREFIX}])
    # порядок важен: сначала кто это, потом CSRF и лимит — 401 раньше 403, лимит — на сотрудника
    root = APIRouter(
        dependencies=[
            Depends(authenticate_staff),
            Depends(csrf_guard),
            Depends(staff_rate_limit),
        ],
        responses=PROBLEM_RESPONSES,
    )
    for router in (*routers, audit_router, config_router):
        root.include_router(router)
    api.include_router(root)
    return api


async def authenticate_staff(request: Request) -> None:
    """Сотрудник из cookie админки; роли — свежие из identity.user_roles."""
    raw = request.session.get(SESSION_KEY)
    member = None
    if isinstance(raw, str):
        try:
            user_id = UserId(UUID(raw))
        except ValueError:
            user_id = None
        if user_id is not None:
            member = await (await container_of(request).get(StaffAuth)).member(user_id)
    if member is None:
        raise NotAuthenticatedError
    request.state.staff = member
    bind_context(user_id=str(member.user_id))


class _PrivateJson:
    """Ответы Admin API: без кэша (в них ПД) и с CSP API — ответ нельзя исполнить или встроить."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_private(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers.setdefault("Content-Security-Policy", API_CSP)
            await send(message)

        await self.app(scope, receive, send_private)


# --- журнал аудита (platform.audit_log) -------------------------------------------------------

audit_router = APIRouter(tags=["audit"])


class AuditRecordOut(BaseModel):
    id: int
    action: str
    actor_kind: str
    actor_id: UUID | None
    entity_type: str | None
    entity_id: UUID | None
    changes: dict[str, Any] | None
    ip: str | None
    created_at: datetime

    @classmethod
    def of(cls, record: AuditRecord) -> AuditRecordOut:
        return cls(
            id=record.id,
            action=record.action,
            actor_kind=record.actor_kind.value,
            actor_id=record.actor_id,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            changes=dict(record.changes) if record.changes is not None else None,
            ip=record.ip,
            created_at=record.created_at,
        )


@audit_router.get("/audit-log", response_model=PageOut[AuditRecordOut], **staff_only(ADMIN))
@inject
async def list_audit_log(
    page: PageParams,
    reader: FromDishka[AuditReader],
    action: Annotated[
        str | None,
        Query(
            max_length=128,
            description="Действие или его начало до точки: `moderation.case` — все с кейсами",
        ),
    ] = None,
    actor_id: UUID | None = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> PageOut[AuditRecordOut]:
    """Журнал действий, новые первыми (только admin)."""
    found = await reader.records(
        AuditFilter(
            action=action,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            since=since,
            until=until,
        ),
        page,
    )
    return PageOut.of(found, AuditRecordOut.of)


# --- feature flags и client-config (platform/http/admin_config.py) ----------------------------

config_router = APIRouter(tags=["config"])


class FeatureFlagOut(BaseModel):
    key: str
    enabled: bool
    public: bool = Field(description="Виден в GET /client-config (Mini App)")
    description: str
    value: Any | None = Field(description="Параметр флага: меняется вместе с кодом, здесь — чтение")
    updated_at: datetime
    updated_by: UUID | None

    @classmethod
    def of(cls, row: Any) -> FeatureFlagOut:
        return cls(**{key: row[key] for key in cls.model_fields})


class FeatureFlagPatchIn(BaseModel):
    enabled: bool


class ClientConfigOut(BaseModel):
    key: str
    value: Any
    editable: bool = Field(description="min_versions и legal_versions; остальное — чтение")
    updated_at: datetime
    updated_by: UUID | None

    @classmethod
    def of(cls, row: Any) -> ClientConfigOut:
        return cls(
            key=row["key"],
            value=row["value"],
            editable=row["key"] in EDITABLE_CONFIG,
            updated_at=row["updated_at"],
            updated_by=row["updated_by"],
        )


class ClientConfigIn(BaseModel):
    value: Any = Field(
        description='min_versions: {"tma": "1.2.0"}; legal_versions: {"terms": "…", "privacy":'
        ' "…"} — версии, чей текст уже лежит в content/legal'
    )


@config_router.get("/feature-flags", response_model=PageOut[FeatureFlagOut], **staff_only(ADMIN))
@inject
async def list_feature_flags(
    page: PageParams, session: FromDishka[AsyncSession]
) -> PageOut[FeatureFlagOut]:
    """Флаги по ключу. Новые флаги заводит миграция: их имена знает код."""
    found = await AdminRows(session).page(table_of(FeatureFlagAdmin), page, key="key", key_type=str)
    return PageOut.of(found, FeatureFlagOut.of)


@config_router.patch("/feature-flags/{key}", response_model=FeatureFlagOut, **staff_only(ADMIN))
async def update_feature_flag(
    key: str, body: FeatureFlagPatchIn, request: Request
) -> FeatureFlagOut:
    """Включить или выключить флаг (только `enabled`); аудит `platform.feature_flag.updated`."""
    model = await apply_change(request, FeatureFlagAdmin(), key, {"enabled": body.enabled})
    if model is None:
        raise NotFoundError(flag=key)
    return FeatureFlagOut.of(as_row(model))


@config_router.get("/client-config", response_model=PageOut[ClientConfigOut], **staff_only(ADMIN))
@inject
async def list_client_config(
    page: PageParams, session: FromDishka[AsyncSession]
) -> PageOut[ClientConfigOut]:
    """Строки client-config в БД; значения окружения меняются деплоем и здесь не видны."""
    found = await AdminRows(session).page(
        table_of(ClientConfigAdmin), page, key="key", key_type=str
    )
    return PageOut.of(found, ClientConfigOut.of)


@config_router.put("/client-config/{key}", response_model=ClientConfigOut, **staff_only(ADMIN))
async def update_client_config(key: str, body: ClientConfigIn, request: Request) -> ClientConfigOut:
    """Заменить значение строки с той же проверкой, что раздел SQLAdmin (422 с причиной); аудит
    `platform.client_config.updated`. Этот процесс видит правку сразу, остальные — за TTL кэша
    (30 с), Mini App — после max-age GET /client-config (60 с)."""
    model = await apply_change(request, ClientConfigAdmin(), key, {"value": body.value})
    if model is None:
        raise NotFoundError(config=key)
    return ClientConfigOut.of(as_row(model))
