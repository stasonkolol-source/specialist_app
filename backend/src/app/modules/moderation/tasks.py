"""Задачи moderation (ADR-0020 §3).

- `moderation.rate_limit_signals` — раз в 15 минут: сигналы риска по систематическим 429
  (ARCHITECTURE §13.3).
"""

from app.modules.moderation.application.use_cases.record_rate_limit_signals import (
    RecordRateLimitSignals,
    RecordRateLimitSignalsCommand,
)
from app.platform.queue.tasks import PeriodicRun, periodic


@periodic("moderation.rate_limit_signals", cron="4,19,34,49 * * * *")
async def rate_limit_signals(run: PeriodicRun) -> None:
    async with run.container() as request:
        record = await request.get(RecordRateLimitSignals)
        await record(RecordRateLimitSignalsCommand())
