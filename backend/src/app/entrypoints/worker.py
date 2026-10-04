"""Процесс воркера (DEVELOPMENT_PLAN 0.12): `python -m app.entrypoints.worker [--role …]`.

Роли: `worker` — очереди default и notifications, `worker-media` — очередь media
(тяжёлая обработка фото и видео отдельно, ARCHITECTURE §5.7). У очереди роли свой пул
со своей параллельностью (§12.2): рассылка уведомлений, которая ждёт слотов лимитера
Telegram, не занимает места обработчиков событий и периодических задач (heartbeat).
Пулы — воркеры Procrastinate в одном процессе; SIGINT и SIGTERM останавливают все сразу.
"""

import argparse
import asyncio
import signal
from dataclasses import dataclass

import procrastinate
import structlog
from procrastinate.worker import Worker
from prometheus_client import CollectorRegistry

from app.entrypoints._wiring import make_worker_container
from app.interfaces.worker.registration import register_worker_tasks
from app.platform.observability.logging import configure_logging
from app.platform.observability.metrics import metrics_server
from app.platform.observability.sentry import init_sentry
from app.platform.queue.tasks import CONTAINER_KEY
from app.platform.settings import Settings, describe


@dataclass(frozen=True, slots=True)
class Pool:
    queue: str
    concurrency: int


ROLES: dict[str, tuple[Pool, ...]] = {
    "worker": (Pool("default", 8), Pool("notifications", 4)),
    "worker-media": (Pool("media", 2),),
}

log = structlog.get_logger(__name__)


async def run(role: str) -> None:
    settings = Settings()
    configure_logging(settings.app)
    init_sentry(settings, process=role)
    pools = ROLES[role]
    container = make_worker_container(settings)
    try:
        app = await container.get(procrastinate.App)
        register_worker_tasks(app)
        workers = [
            Worker(
                app=app,
                queues=[pool.queue],
                concurrency=pool.concurrency,
                name=f"{role}:{pool.queue}",
                additional_context={CONTAINER_KEY: container},
                install_signal_handlers=False,  # обработчик один на все пулы — ниже
            )
            for pool in pools
        ]

        def stop() -> None:
            for worker in workers:
                worker.stop()  # type: ignore[no-untyped-call]  # procrastinate без аннотаций

        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop)
        log.info(
            "worker_started", role=role, queues=[pool.queue for pool in pools], **describe(settings)
        )
        # лаг очередей и read-model, 429 Telegram — в реестре процесса; наружу — METRICS_PORT
        with metrics_server(settings.metrics, await container.get(CollectorRegistry)):
            await asyncio.gather(*(worker.run() for worker in workers))  # type: ignore[no-untyped-call]
    finally:
        await container.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Воркер задач «Соседей»")
    parser.add_argument("--role", choices=sorted(ROLES), default="worker")
    asyncio.run(run(parser.parse_args().role))


if __name__ == "__main__":
    main()
