"""Ночная `platform.retention_sweep` (ARCHITECTURE §7.10, §12.3; DEVELOPMENT_PLAN 2.12b).

Проходит правила модулей из реестра по очереди. Правило удаляет своё короткими транзакциями и
само пропускает сущности под legal hold (порт RetentionHold). Сбой одного правила не мешает
остальным: ошибка — в Sentry и лог, следующий проход повторит.
"""

from datetime import datetime

import sentry_sdk
import structlog
from dishka import AsyncContainer

from app.platform.kernel.clock import Clock
from app.platform.privacy.registry import PRIVACY, PrivacyRegistry, RetentionRun
from app.platform.queue.tasks import PeriodicRun, periodic

log = structlog.get_logger(__name__)


async def sweep(
    container: AsyncContainer, *, now: datetime, registry: PrivacyRegistry = PRIVACY
) -> dict[str, int]:
    """Исполнить все правила на момент `now`: сколько удалено по каждому (сбой — -1)."""
    report: dict[str, int] = {}
    for rule in registry.rules.values():
        try:
            report[rule.name] = await rule.handler(RetentionRun(container=container, now=now))
        except Exception:
            sentry_sdk.capture_exception()
            log.exception("retention_rule_failed", rule=rule.name)
            report[rule.name] = -1
    purged = {name: count for name, count in report.items() if count}
    if purged:
        log.info("retention_sweep_done", **purged)
    return report


@periodic("platform.retention_sweep", cron="37 3 * * *")
async def retention_sweep(run: PeriodicRun) -> None:
    """Ночью, после `procrastinate.remove_old_jobs` (03:17): матрица сроков §7.10."""
    clock = await run.container.get(Clock)
    await sweep(run.container, now=clock.now())
