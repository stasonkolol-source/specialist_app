"""Воркер и периодические задачи (DEVELOPMENT_PLAN 0.12).

Готово, когда: use case → событие → задача подписчика выполнена воркером; heartbeat в
логе; упавшая задача повторяется с задержкой.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

import procrastinate
import pytest
import pytest_asyncio
from dishka import AsyncContainer, FromDishka
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

from app.entrypoints._wiring import load_module_tasks, make_container
from app.interfaces.worker.registration import register_worker_tasks
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import ExternalServiceError
from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import new_id
from app.platform.observability.metrics import QueueMetrics
from app.platform.queue.periodic import queue_lag
from app.platform.queue.port import TaskRef
from app.platform.queue.tasks import (
    CONTAINER_KEY,
    QUEUES,
    JitteredRetry,
    PeriodicRun,
    TaskRegistry,
    register_tasks,
    subscriber,
    task,
)
from app.platform.settings import Settings

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True, kw_only=True)
class GreetingSent(DomainEvent):
    event_type = "sample.GreetingSent"
    greeting_id: UUID


@dataclass(frozen=True, slots=True)
class FlakyPayload:
    note: str


ON_GREETING_SENT: Final = TaskRef("sample.on_greeting_sent", GreetingSent)
FLAKY: Final = TaskRef("sample.flaky", FlakyPayload)

TEST_TASKS = TaskRegistry()
handled: list[tuple[UUID, str]] = []


@subscriber(GreetingSent, ON_GREETING_SENT, registry=TEST_TASKS)
async def on_greeting_sent(event: GreetingSent, session: FromDishka[AsyncSession]) -> None:
    user = (await session.execute(text("SELECT current_user"))).scalar_one()
    handled.append((event.greeting_id, user))


@task(FLAKY, retry=JitteredRetry(max_attempts=3, base_seconds=10), registry=TEST_TASKS)
async def flaky(payload: FlakyPayload) -> None:
    raise ExternalServiceError(note=payload.note)


async def send_greeting(uow: UnitOfWork, clock: Clock, *, fail: bool = False) -> UUID:
    """Use case: пишет событие в UoW, диспетчер ставит подписчиков в той же транзакции."""
    greeting_id = new_id()
    async with uow:
        uow.add_event(GreetingSent(greeting_id=greeting_id, occurred_at=clock.now()))
        if fail:
            raise RuntimeError("use case failed")
    return greeting_id


@pytest_asyncio.fixture(loop_scope="session")
async def container(settings: Settings) -> AsyncIterator[AsyncContainer]:
    handled.clear()
    container = make_container(settings, registry=TEST_TASKS.event_registry())
    app = await container.get(procrastinate.App)
    # как воркер: без этого задачи модулей видны, только если их импортировал другой тест
    load_module_tasks()
    register_worker_tasks(app)
    register_tasks(app, TEST_TASKS)
    await _clear_jobs(container)
    try:
        yield container
    finally:
        await _clear_jobs(container)
        await container.close()


async def _clear_jobs(container: AsyncContainer) -> None:
    async with container() as request:
        session = await request.get(AsyncSession)
        await session.execute(text("DELETE FROM procrastinate_jobs"))
        await session.commit()


async def _run_worker(container: AsyncContainer, *queues: str) -> None:
    app = await container.get(procrastinate.App)
    await app.run_worker_async(
        queues=list(queues) or ["default"],
        wait=False,
        concurrency=1,
        additional_context={CONTAINER_KEY: container},
    )


async def _jobs(container: AsyncContainer, task_name: str) -> list[dict[str, object]]:
    async with container() as request:
        session = await request.get(AsyncSession)
        rows = await session.execute(
            text(
                "SELECT status::text, attempts, scheduled_at FROM procrastinate_jobs"
                " WHERE task_name = :name ORDER BY id"
            ),
            {"name": task_name},
        )
        return [dict(row._mapping) for row in rows]


async def test_event_from_use_case_is_handled_by_worker(container: AsyncContainer) -> None:
    async with container() as request:
        greeting_id = await send_greeting(await request.get(UnitOfWork), await request.get(Clock))

    await _run_worker(container)

    assert handled == [(greeting_id, "app")]
    [job] = await _jobs(container, ON_GREETING_SENT.name)
    assert job["status"] == "succeeded"


async def test_rolled_back_use_case_enqueues_nothing(container: AsyncContainer) -> None:
    async with container() as request:
        with pytest.raises(RuntimeError, match="use case failed"):
            await send_greeting(await request.get(UnitOfWork), await request.get(Clock), fail=True)

    await _run_worker(container)

    assert handled == []
    assert await _jobs(container, ON_GREETING_SENT.name) == []


async def test_failed_task_is_retried_with_delay(container: AsyncContainer) -> None:
    app = await container.get(procrastinate.App)
    before = datetime.now(UTC)
    await app.configure_task(FLAKY.name).defer_async(payload={"note": "provider is down"})

    await _run_worker(container)

    [job] = await _jobs(container, FLAKY.name)
    assert job["status"] == "todo"
    assert job["attempts"] == 1
    delay = job["scheduled_at"] - before  # type: ignore[operator]
    assert timedelta(seconds=4) <= delay <= timedelta(seconds=20)


async def test_heartbeat_is_logged(container: AsyncContainer) -> None:
    app = await container.get(procrastinate.App)
    await app.configure_task("ops.heartbeat").defer_async(timestamp=0)

    with capture_logs() as logs:
        await _run_worker(container)

    assert any(entry["event"] == "ops_heartbeat" for entry in logs)
    jobs = await _jobs(container, "ops.heartbeat")  # периодический deferrer мог добавить свою
    assert jobs
    assert {job["status"] for job in jobs} == {"succeeded"}


async def test_platform_periodic_tasks_are_scheduled(container: AsyncContainer) -> None:
    app = await container.get(procrastinate.App)
    periodic = {task.task.name: task.cron for task in app.periodic_registry.periodic_tasks.values()}
    assert periodic == {
        "procrastinate.retry_stalled_jobs": "*/5 * * * *",
        "procrastinate.remove_old_jobs": "17 3 * * *",
        "ops.heartbeat": "* * * * *",
        "ops.queue_lag": "* * * * *",
        "platform.idempotency_cleanup": "23 * * * *",
        "media.cleanup_orphans": "41 * * * *",
        "media.purge_deleted": "37 * * * *",
        "media.retry_stuck": "*/15 * * * *",
        "media.hide_deleted": "7,22,37,52 * * * *",
        "notifications.expire_stale": "53 * * * *",
    }


async def test_queue_lag_is_measured_for_every_queue(container: AsyncContainer) -> None:
    app = await container.get(procrastinate.App)
    metrics = await container.get(QueueMetrics)

    await queue_lag(PeriodicRun(app=app, container=container, timestamp=0))

    for queue in QUEUES:
        assert metrics.lag.labels(queue=queue)._value.get() >= 0
