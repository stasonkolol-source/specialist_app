"""Фабрика FastAPI (DEVELOPMENT_PLAN 0.13a, ARCHITECTURE §8).

Роутеры модулей (`modules/<m>/http/router.py`) собирает композиционный корень
(entrypoints/_wiring.py) и передаёт сюда; BFF-роутеры `views/` интерфейс подключает сам.
"""

from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from dishka import AsyncContainer
from dishka.integrations.fastapi import setup_dishka
from fastapi import APIRouter, FastAPI
from prometheus_client import CollectorRegistry

from app.interfaces.http import client_config, system, views
from app.interfaces.http.client import ClientPolicy
from app.interfaces.http.errors import Problems, install_error_handlers
from app.interfaces.http.middleware import RequestContextMiddleware
from app.interfaces.http.openapi import API_TITLE, API_VERSION, PROBLEM_RESPONSES, install_openapi
from app.interfaces.http.operation_ids import operation_id
from app.interfaces.http.proxy import ClientAddressMiddleware
from app.interfaces.http.security_headers import SecurityHeadersMiddleware
from app.interfaces.http.warmup import warm_up_web
from app.platform.config.cache import ClientConfigCache
from app.platform.config.port import MAINTENANCE_FLAG
from app.platform.i18n.translator import Translator
from app.platform.legal.port import LegalLibrary
from app.platform.observability.metrics import HttpMetrics, metrics_server
from app.platform.settings import Environment, Settings

API_PREFIX = "/api/v1"
DOCS_PATH = f"{API_PREFIX}/docs"
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_app(
    container: AsyncContainer,
    settings: Settings,
    routers: Sequence[APIRouter] = (),
    *,
    translator: Translator | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # тексты правовых документов проверяются при старте: ошибка в них не выпускает релиз,
        # а не роняет GET /client-config у всех клиентов
        await container.get(LegalLibrary)
        await warm_up_web(container)  # первый запрос после рестарта не ждёт соединений
        # метрики — на своём внутреннем порту, не на порту API (3.3)
        with metrics_server(settings.metrics, await container.get(CollectorRegistry)):
            yield
        await container.close()

    public_docs = settings.app.env is not Environment.PRODUCTION
    app = _fastapi(public_docs=public_docs, lifespan=lifespan)
    problems = Problems(
        base_url=settings.app.api_public_url, translator=translator or Translator.load()
    )
    install_error_handlers(app, problems)

    async def client_policy() -> ClientPolicy:
        """Минимальные версии: из client-config (правит админка), запасные — из настроек."""
        snapshot = await (await container.get(ClientConfigCache)).get()
        return ClientPolicy({**settings.app.min_client_versions, **snapshot.min_versions})

    async def maintenance() -> bool:
        """Техработы: публичный флаг `platform.maintenance` правит админка, без деплоя."""
        return await (await container.get(ClientConfigCache)).is_enabled(MAINTENANCE_FLAG)

    async def http_metrics() -> HttpMetrics:
        return await container.get(HttpMetrics)

    app.add_middleware(
        RequestContextMiddleware,
        problems=problems,
        clients=client_policy,
        api_prefix=API_PREFIX,
        maintenance=maintenance,
        metrics=http_metrics,
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        api_prefix=API_PREFIX,
        docs_path=DOCS_PATH if public_docs else None,
    )
    # внешний слой: адрес клиента и схема нужны всем остальным (лимиты, HSTS, журнал согласий)
    app.add_middleware(
        ClientAddressMiddleware,
        trusted_proxies=settings.app.trusted_proxies,
        cloudflare=settings.app.cloudflare_ips,
    )

    _mount(app, routers)
    setup_dishka(container, app)
    return app


def openapi_spec(routers: Sequence[APIRouter]) -> dict[str, Any]:
    """Схема OpenAPI без контейнера и настроек: для `cli openapi` и проверки в CI."""
    app = _fastapi(public_docs=True)
    _mount(app, routers)
    return app.openapi()


def _fastapi(*, public_docs: bool, lifespan: Lifespan | None = None) -> FastAPI:
    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        openapi_url=f"{API_PREFIX}/openapi.json" if public_docs else None,
        docs_url=DOCS_PATH if public_docs else None,
        redoc_url=None,
        generate_unique_id_function=operation_id,
        lifespan=lifespan,
    )
    install_openapi(app)
    return app


def _mount(app: FastAPI, routers: Sequence[APIRouter]) -> None:
    api = APIRouter(prefix=API_PREFIX, responses=PROBLEM_RESPONSES)
    for router in (*routers, views.router, client_config.router):
        api.include_router(router)
    app.include_router(api)
    app.include_router(system.router)
