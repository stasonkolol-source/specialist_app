"""Админка `/admin` в процессе web (DEVELOPMENT_PLAN 2.7a–b; ADR-0009, ADR-0020 §1).

SQLAdmin монтируется в приложение FastAPI рядом с `/api/v1`; разделы — `admin/views.py`
модулей (ORM-классы своего модуля, решения по агрегатам — через use case) и разделы платформы:
feature flags, client-config, журнал аудита (interfaces/admin/views.py). Вход —
interfaces/admin/auth.py. На stage и проде без APP_ADMIN_SESSION_KEY админка не монтируется: её
публикуют только за Cloudflare Access (K31, шаги 0.25 и 3.1). JSON-API для тех же разделов —
Admin API `/admin/api/v1` (interfaces/http/admin_api.py): монтируется раньше SQLAdmin, с той же
cookie персонала.

Сессии SQLAdmin берут движок процесса из DI при первом запросе (`_BindEngine`): фабрика
приложения синхронна, а движок — ресурс APP-скоупа контейнера.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Final

import structlog
from fastapi import FastAPI
from sqladmin import Admin, BaseView, ModelView
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.interfaces.admin.auth import StaffAuthBackend
from app.interfaces.admin.views import VIEWS as PLATFORM_VIEWS
from app.modules.catalog.admin.views import VIEWS as CATALOG_VIEWS
from app.modules.geo.admin.views import VIEWS as GEO_VIEWS
from app.modules.identity.admin.views import VIEWS as IDENTITY_VIEWS
from app.modules.moderation.admin.views import VIEWS as MODERATION_VIEWS
from app.modules.notifications.admin.views import VIEWS as NOTIFICATIONS_VIEWS
from app.modules.specialists.admin.views import VIEWS as SPECIALISTS_VIEWS
from app.platform.http.admin import LOCKS_INFO, AdminSession
from app.platform.http.staff import PUBLISHED, session_secret
from app.platform.settings import Settings

log = structlog.get_logger(__name__)

BASE_URL: Final = "/admin"
TEMPLATES: Final = Path(__file__).parent / "templates"

VIEWS: Final[Sequence[type[ModelView | BaseView]]] = (
    *MODERATION_VIEWS,
    *IDENTITY_VIEWS,
    *SPECIALISTS_VIEWS,
    *CATALOG_VIEWS,
    *GEO_VIEWS,
    *NOTIFICATIONS_VIEWS,
    *PLATFORM_VIEWS,
)


def mount_admin(app: FastAPI, settings: Settings) -> Admin | None:
    """SQLAdmin на `/admin`; None — админка выключена (stage или прод без ключа сессии)."""
    secret = session_secret(settings.app)
    if secret is None:
        log.warning("admin_disabled", reason="APP_ADMIN_SESSION_KEY is not set")
        return None
    maker = async_sessionmaker(
        class_=AsyncSession, sync_session_class=AdminSession, expire_on_commit=False
    )
    admin = Admin(
        app,
        session_maker=maker,
        base_url=BASE_URL,
        title="Соседи — админка",
        templates_dir=str(TEMPLATES),
        authentication_backend=StaffAuthBackend(secret, https_only=settings.app.env in PUBLISHED),
        middlewares=[Middleware(_BindEngine, maker=maker)],
    )
    locks: dict[type, int] = {}
    for view in VIEWS:
        admin.add_view(view)
        lock = getattr(view, "advisory_lock", None)
        model = getattr(view, "model", None)
        if lock is not None and model is not None:
            locks[model] = lock
    maker.configure(info={LOCKS_INFO: locks})
    return admin


class _BindEngine:
    """Привязать фабрику сессий SQLAdmin к движку процесса при первом запросе."""

    def __init__(self, app: ASGIApp, maker: async_sessionmaker[AsyncSession]) -> None:
        self._app, self._maker = app, maker

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._maker.kw.get("bind") is None:
            container = Request(scope).state.dishka_container
            self._maker.configure(bind=await container.get(AsyncEngine))
        await self._app(scope, receive, send)
