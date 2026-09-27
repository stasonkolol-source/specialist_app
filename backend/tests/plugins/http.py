"""HTTP-клиент тестов поверх ASGI: приложение и контейнер из настроек теста."""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter

from app.entrypoints._wiring import make_web_container
from app.interfaces.http.app import create_app
from app.platform.settings import Settings


@asynccontextmanager
async def http_client(
    settings: Settings, *routers: APIRouter, client_ip: str = "127.0.0.1"
) -> AsyncIterator[httpx.AsyncClient]:
    """Клиент к приложению с роутерами теста; ошибки приложения — ответами, а не исключениями."""
    container = make_web_container(settings)
    try:
        app = create_app(container, settings, list(routers))
        transport = httpx.ASGITransport(
            app=app, raise_app_exceptions=False, client=(client_ip, 50000)
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        await container.close()


def sample_router(prefix: str = "/test") -> APIRouter:
    """Роутер тестовых обработчиков: operationId `test_<функция>` вместо правила модулей."""
    return APIRouter(prefix=prefix, generate_unique_id_function=lambda route: f"test_{route.name}")


__all__: Sequence[str] = ("http_client", "sample_router")
