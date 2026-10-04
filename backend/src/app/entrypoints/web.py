"""Процесс web (DEVELOPMENT_PLAN 0.13a): `python -m app.entrypoints.web`.

uvicorn слушает APP_WEB_HOST:APP_WEB_PORT (локально 127.0.0.1:8000, в образе 0.0.0.0 за
kamal-proxy, ARCHITECTURE §5.7).
Для разработки — `make dev-web` (uvicorn --factory --reload).
"""

import structlog
import uvicorn
from fastapi import FastAPI

from app.entrypoints._wiring import make_web_container, module_routers
from app.interfaces.admin.app import mount_admin
from app.interfaces.http.app import create_app
from app.platform.i18n.translator import Translator
from app.platform.observability.logging import configure_logging
from app.platform.observability.sentry import init_sentry
from app.platform.settings import AppSettings, Settings, describe

log = structlog.get_logger(__name__)


def create() -> FastAPI:
    """Фабрика для uvicorn: настройки, логи, Sentry, контейнер и приложение."""
    settings = Settings()
    configure_logging(settings.app)
    init_sentry(settings)
    translator = Translator.load()
    container = make_web_container(settings, translator)
    app = create_app(container, settings, module_routers(), translator=translator)
    mount_admin(app, settings)  # /admin — SQLAdmin, вход персонала (2.7a)
    log.info("web_started", **describe(settings))
    return app


def main() -> None:
    app = AppSettings()
    uvicorn.run(
        "app.entrypoints.web:create",
        factory=True,
        host=app.web_host,
        port=app.web_port,
        access_log=False,  # access-лог пишет RequestContextMiddleware в формате structlog
        log_config=None,
        proxy_headers=True,
        # X-Forwarded-For принимаем от kamal-proxy в сети контейнеров; локально — только loopback
        forwarded_allow_ips="*" if app.web_host == "0.0.0.0" else "127.0.0.1",  # noqa: S104
    )


if __name__ == "__main__":
    main()
