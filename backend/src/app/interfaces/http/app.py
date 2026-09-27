"""Фабрика FastAPI (DEVELOPMENT_PLAN 0.13a, ARCHITECTURE §8).

Роутеры модулей (`modules/<m>/http/router.py`) собирает композиционный корень
(entrypoints/_wiring.py) и передаёт сюда; BFF-роутеры `views/` интерфейс подключает сам.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from dishka import AsyncContainer
from dishka.integrations.fastapi import setup_dishka
from fastapi import APIRouter, FastAPI

from app.interfaces.http import system, views
from app.interfaces.http.client import ClientPolicy
from app.interfaces.http.errors import Problems, install_error_handlers
from app.interfaces.http.middleware import RequestContextMiddleware
from app.interfaces.http.operation_ids import operation_id
from app.platform.settings import Environment, Settings

API_PREFIX = "/api/v1"


def create_app(
    container: AsyncContainer, settings: Settings, routers: Sequence[APIRouter] = ()
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await container.close()

    public_docs = settings.app.env is not Environment.PRODUCTION
    app = FastAPI(
        title="Сосед API",
        version=settings.app.release,
        openapi_url=f"{API_PREFIX}/openapi.json" if public_docs else None,
        docs_url=f"{API_PREFIX}/docs" if public_docs else None,
        redoc_url=None,
        generate_unique_id_function=operation_id,
        lifespan=lifespan,
    )
    problems = Problems(base_url=settings.app.api_public_url)
    install_error_handlers(app, problems)
    app.add_middleware(
        RequestContextMiddleware,
        problems=problems,
        clients=ClientPolicy(settings.app.min_client_versions),
        api_prefix=API_PREFIX,
    )

    api = APIRouter(prefix=API_PREFIX)
    for router in (*routers, views.router):
        api.include_router(router)
    app.include_router(api)
    app.include_router(system.router)
    setup_dishka(container, app)
    return app
