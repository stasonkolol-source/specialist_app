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

from app.interfaces.http import client_config, system, views
from app.interfaces.http import spike as spike_router
from app.interfaces.http.client import ClientPolicy
from app.interfaces.http.errors import Problems, install_error_handlers
from app.interfaces.http.middleware import RequestContextMiddleware
from app.interfaces.http.openapi import API_TITLE, API_VERSION, PROBLEM_RESPONSES, install_openapi
from app.interfaces.http.operation_ids import operation_id
from app.platform.config.cache import ClientConfigCache
from app.platform.i18n.translator import Translator
from app.platform.settings import Environment, Settings

API_PREFIX = "/api/v1"
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
        yield
        await container.close()

    app = _fastapi(public_docs=settings.app.env is not Environment.PRODUCTION, lifespan=lifespan)
    problems = Problems(
        base_url=settings.app.api_public_url, translator=translator or Translator.load()
    )
    install_error_handlers(app, problems)

    async def client_policy() -> ClientPolicy:
        """Минимальные версии: из client-config (правит админка), запасные — из настроек."""
        snapshot = await (await container.get(ClientConfigCache)).get()
        return ClientPolicy({**settings.app.min_client_versions, **snapshot.min_versions})

    app.add_middleware(
        RequestContextMiddleware,
        problems=problems,
        clients=client_policy,
        api_prefix=API_PREFIX,
    )

    _mount(app, routers, spike=settings.app.env is Environment.DEV)
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
        docs_url=f"{API_PREFIX}/docs" if public_docs else None,
        redoc_url=None,
        generate_unique_id_function=operation_id,
        lifespan=lifespan,
    )
    install_openapi(app)
    return app


def _mount(app: FastAPI, routers: Sequence[APIRouter], *, spike: bool = False) -> None:
    api = APIRouter(prefix=API_PREFIX, responses=PROBLEM_RESPONSES)
    for router in (*routers, views.router, client_config.router):
        api.include_router(router)
    if spike:
        # спайк 0.24: только dev и вне OpenAPI; удаляется в 2.1
        api.include_router(spike_router.router)
    app.include_router(api)
    app.include_router(system.router)
