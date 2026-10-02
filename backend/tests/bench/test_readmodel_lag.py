"""Лаг read-model поиска (DEVELOPMENT_PLAN 4.1): p95 < 10 с на прогоне из 1 000 событий.

Вручную: `uv run pytest -m bench -k readmodel_lag`. Сто опубликованных профилей; 1 000 событий
ProfileUpdated разом — худший случай. Воркер с параллельностью пула default отрабатывает
подписчики и пересборки. Лаг — от события до новой строки, как у метрики
`search_index_lag_seconds`; тест печатает p50, p95 и максимум.
"""

import statistics
import time
from collections.abc import AsyncIterator
from itertools import batched

import procrastinate
import pytest
from dishka import AsyncContainer

from app.entrypoints._wiring import load_module_tasks, make_worker_container
from app.entrypoints.worker import ROLES
from app.interfaces.worker.registration import register_worker_tasks
from app.modules.search.application.ports import ON_PROFILE_UPDATED
from app.modules.search.infrastructure.metrics import PrometheusIndexMetrics
from app.platform.contracts.events.specialists import ProfileUpdated
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.queue.port import JobQueue
from app.platform.queue.tasks import CONTAINER_KEY
from app.platform.settings import Settings
from tests.plugins.search import Specialist

pytestmark = pytest.mark.bench

PROFILES = 100
EVENTS = 1_000
PER_TRANSACTION = 100
CONCURRENCY = next(pool.concurrency for pool in ROLES["worker"] if pool.queue == "default")
TARGET_P95 = 10.0
MAX_RUNS = 50


@pytest.fixture
async def container(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(storage_settings)
    load_module_tasks()
    register_worker_tasks(await container.get(procrastinate.App))
    try:
        yield container
    finally:
        await container.close()


async def _drain(container: AsyncContainer, probe: Specialist) -> None:
    """Воркер, пока есть отметки и задачи search: без ожидания он выходит, когда очередь пуста,
    а пересборка ставит себя снова, пока отметки не кончатся."""
    app = await container.get(procrastinate.App)
    for _ in range(MAX_RUNS):
        left = await probe.scalar(
            "SELECT (SELECT count(*) FROM search.pending_profiles)"
            " + (SELECT count(*) FROM procrastinate_jobs WHERE task_name LIKE 'search.%'"
            " AND status = 'todo' AND (scheduled_at IS NULL OR scheduled_at <= now()))"
        )
        if not left:
            return
        await app.run_worker_async(
            queues=["default"],
            wait=False,
            concurrency=CONCURRENCY,
            additional_context={CONTAINER_KEY: container},
        )
    pytest.fail("read-model не догнал события")


async def test_readmodel_lag_p95(
    container: AsyncContainer, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    specialists = [Specialist(container) for _ in range(PROFILES)]
    for specialist in specialists:
        await specialist.publish()
    probe = specialists[0]
    # подписчики сида (модерация, уведомления) замеру не нужны; строки сида — до замера
    await probe.execute(
        "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND task_name NOT LIKE 'search.%'"
    )
    await _drain(container, probe)
    lags: list[float] = []
    observe = PrometheusIndexMetrics.observe_lag

    def recording(self: PrometheusIndexMetrics, seconds: float) -> None:
        lags.append(seconds)
        observe(self, seconds)

    monkeypatch.setattr(PrometheusIndexMetrics, "observe_lag", recording)

    started = time.monotonic()
    async with container() as request:
        uow, queue = await request.get(UnitOfWork), await request.get(JobQueue)
        clock = await request.get(Clock)
        for chunk in batched(range(EVENTS), PER_TRANSACTION, strict=True):
            async with uow:
                for number in chunk:
                    author = specialists[number % PROFILES]
                    event = ProfileUpdated(
                        profile_id=author.profile_id,
                        user_id=author.user_id,
                        fields=("headline",),
                        occurred_at=clock.now(),
                    )
                    await queue.enqueue(ON_PROFILE_UPDATED, event)
    await _drain(container, probe)
    elapsed = time.monotonic() - started

    assert lags, "пересборок не было"
    p50 = statistics.median(lags)
    p95 = statistics.quantiles(lags, n=20, method="inclusive")[-1]
    with capsys.disabled():
        print(
            f"\nreadmodel_lag: {EVENTS} событий по {PROFILES} профилям за {elapsed:.1f} с,"
            f" {len(lags)} пересборок строк; p50 {p50:.2f} с, p95 {p95:.2f} с,"
            f" максимум {max(lags):.2f} с (порог p95 {TARGET_P95:.0f} с)"
        )
    assert p95 < TARGET_P95
