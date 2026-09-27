"""Процесс воркера (DEVELOPMENT_PLAN 0.12): `python -m app.entrypoints.worker [--role …]`.

Роли: `worker` — очереди default и notifications, `worker-media` — очередь media
(тяжёлая обработка фото и видео отдельно, ARCHITECTURE §5.7).
"""

import argparse
import asyncio

import procrastinate
import structlog

from app.entrypoints._wiring import make_worker_container
from app.interfaces.worker.registration import register_worker_tasks
from app.platform.observability.logging import configure_logging
from app.platform.observability.sentry import init_sentry
from app.platform.queue.tasks import CONTAINER_KEY
from app.platform.settings import Settings, describe

ROLES: dict[str, tuple[list[str], int]] = {
    "worker": (["default", "notifications"], 8),
    "worker-media": (["media"], 2),
}

log = structlog.get_logger(__name__)


async def run(role: str) -> None:
    settings = Settings()
    configure_logging(settings.app)
    init_sentry(settings)
    queues, concurrency = ROLES[role]
    container = make_worker_container(settings)
    try:
        app = await container.get(procrastinate.App)
        register_worker_tasks(app)
        log.info("worker_started", role=role, queues=queues, **describe(settings))
        await app.run_worker_async(
            queues=queues,
            concurrency=concurrency,
            additional_context={CONTAINER_KEY: container},
            name=role,
        )
    finally:
        await container.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Воркер задач «Соседа»")
    parser.add_argument("--role", choices=sorted(ROLES), default="worker")
    asyncio.run(run(parser.parse_args().role))


if __name__ == "__main__":
    main()
