"""Контракт OpenAPI против живого приложения (DEVELOPMENT_PLAN 0.20, ADR-0020 §15).

schemathesis генерирует запросы по `backend/openapi.json` и проверяет, что ответ описан
схемой: статус, content-type (ошибки — application/problem+json), тело, и что сервер не
отвечает 5xx. Приложение — настоящий uvicorn в отдельном потоке на PostgreSQL и Valkey
из testcontainers: так соединения БД живут в одном цикле событий сервера.
"""

import asyncio
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import schemathesis
import uvicorn
from hypothesis import HealthCheck, settings

from app.entrypoints._wiring import make_web_container, module_routers
from app.interfaces.http.app import create_app
from app.platform.settings import Settings

pytestmark = pytest.mark.integration

OPENAPI = Path(__file__).resolve().parents[2] / "openapi.json"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def live_api(settings: Settings) -> Iterator[str]:
    """uvicorn с приложением теста в своём потоке и цикле событий."""
    port = _free_port()
    app = create_app(make_web_container(settings), settings, module_routers())
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, lifespan="on")
    )
    thread = threading.Thread(target=lambda: asyncio.run(server.serve()), daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        threading.Event().wait(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


schema = schemathesis.openapi.from_path(OPENAPI)


@schema.parametrize()
@settings(
    max_examples=25,
    deadline=None,
    database=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_api_matches_contract(case: schemathesis.Case, live_api: str) -> None:
    case.call_and_validate(base_url=live_api)
