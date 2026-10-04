"""Периодические задачи платформы (DEVELOPMENT_PLAN 0.12, ARCHITECTURE §12.3)."""

from datetime import timedelta

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.db.port import UnitOfWork
from app.platform.idempotency.port import IdempotencyStore
from app.platform.kernel.clock import Clock
from app.platform.observability.metrics import QueueMetrics
from app.platform.queue.lag import LAG_ALERT_SECONDS, queue_lags
from app.platform.queue.tasks import QUEUES, PeriodicRun, periodic
from app.platform.settings import HealthchecksSettings

log = structlog.get_logger(__name__)

IDEMPOTENCY_TTL = timedelta(hours=24)
HEARTBEAT_TIMEOUT = httpx.Timeout(5.0)
JOB_RETENTION_HOURS = 7 * 24
"""Выполненные задачи храним 7 дней (ARCHITECTURE §7.10)."""


@periodic("procrastinate.retry_stalled_jobs", cron="*/5 * * * *")
async def retry_stalled_jobs(run: PeriodicRun) -> None:
    """Задачи воркеров, которые перестали слать heartbeat, возвращаются в очередь."""
    manager = run.app.job_manager
    stalled = list(await manager.get_stalled_jobs())
    for job in stalled:
        await manager.retry_job(job)
    if stalled:
        log.warning("stalled_jobs_retried", count=len(stalled))


@periodic("procrastinate.remove_old_jobs", cron="17 3 * * *")
async def remove_old_jobs(run: PeriodicRun) -> None:
    """Ночная очистка: выполненные и отменённые задачи старше 7 дней."""
    await run.app.job_manager.delete_old_jobs(
        nb_hours=JOB_RETENTION_HOURS, include_failed=False, include_cancelled=True
    )


@periodic("ops.heartbeat", cron="* * * * *")
async def heartbeat(run: PeriodicRun) -> None:
    """Раз в минуту: запись в лог и, если задан адрес (K33), ping Healthchecks.io.

    Задача идёт в очереди default, как и остальные периодические: пинга нет — значит, воркер
    стоит или пул default забит, и Healthchecks пришлёт алерт о пропуске (3.3).
    """
    log.info("ops_heartbeat")
    url = (await run.container.get(HealthchecksSettings)).worker_ping_url
    if url is None:
        return
    async with httpx.AsyncClient(timeout=HEARTBEAT_TIMEOUT) as client:
        try:
            response = await client.get(url.get_secret_value())
            response.raise_for_status()  # 404 — неверный адрес: проверка молчала бы до алерта
        except httpx.HTTPError as exc:
            # адрес в лог не пишем: по нему любой отметит проверку (masking.py — страховка)
            log.warning("heartbeat_ping_failed", error=type(exc).__name__)


@periodic("ops.queue_lag", cron="* * * * *")
async def queue_lag(run: PeriodicRun) -> None:
    """Раз в минуту: лаг очередей — в метрику, а выше порога (§12.4) — предупреждение."""
    async with run.container() as request:
        lags = await queue_lags(await request.get(AsyncSession))
    metrics = await run.container.get(QueueMetrics)
    for queue in QUEUES:
        lag = lags.get(queue, 0.0)
        metrics.lag.labels(queue=queue).set(lag)
        if lag > LAG_ALERT_SECONDS.get(queue, float("inf")):
            log.warning("queue_lag_high", queue=queue, seconds=round(lag))


@periodic("platform.idempotency_cleanup", cron="23 * * * *")
async def idempotency_cleanup(run: PeriodicRun) -> None:
    """Ключи Idempotency-Key старше 24 ч и зависшие «в работе» после падения процесса."""
    async with run.container() as request:
        uow = await request.get(UnitOfWork)
        store = await request.get(IdempotencyStore)
        clock = await request.get(Clock)
        async with uow:
            removed = await store.cleanup(before=clock.now() - IDEMPOTENCY_TTL)
    if removed:
        log.info("idempotency_keys_removed", count=removed)
