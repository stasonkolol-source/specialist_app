"""Периодические задачи платформы (DEVELOPMENT_PLAN 0.12, ARCHITECTURE §12.3)."""

import httpx
import structlog

from app.platform.queue.tasks import PeriodicRun, periodic
from app.platform.settings import AppSettings

log = structlog.get_logger(__name__)

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
    """Раз в минуту: запись в лог и, если задан адрес (K33), ping Healthchecks.io."""
    log.info("ops_heartbeat")
    settings = await run.container.get(AppSettings)
    if settings.heartbeat_url:
        async with httpx.AsyncClient(timeout=5) as client:
            try:
                await client.get(settings.heartbeat_url)
            except httpx.HTTPError as exc:
                log.warning("heartbeat_ping_failed", error=type(exc).__name__)
