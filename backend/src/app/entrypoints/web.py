"""Процесс web (DEVELOPMENT_PLAN 0.13a): `python -m app.entrypoints.web`.

uvicorn слушает 127.0.0.1:8000, снаружи его закрывает kamal-proxy (ARCHITECTURE §5.7).
Для разработки — `make dev-web` (uvicorn --factory --reload).
"""

import structlog
import uvicorn
from fastapi import FastAPI

from app.entrypoints._wiring import make_web_container, module_routers
from app.interfaces.http.app import create_app
from app.platform.observability.logging import configure_logging
from app.platform.observability.sentry import init_sentry
from app.platform.settings import Settings, describe

HOST = "127.0.0.1"
PORT = 8000

log = structlog.get_logger(__name__)


def create() -> FastAPI:
    """Фабрика для uvicorn: настройки, логи, Sentry, контейнер и приложение."""
    settings = Settings()
    configure_logging(settings.app)
    init_sentry(settings)
    app = create_app(make_web_container(settings), settings, module_routers())
    log.info("web_started", **describe(settings))
    return app


def main() -> None:
    uvicorn.run(
        "app.entrypoints.web:create",
        factory=True,
        host=HOST,
        port=PORT,
        access_log=False,  # access-лог пишет RequestContextMiddleware в формате structlog
        log_config=None,
        proxy_headers=True,
        forwarded_allow_ips=HOST,
    )


if __name__ == "__main__":
    main()
