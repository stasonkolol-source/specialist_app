"""Задачи moderation (ADR-0020 §3).

- `moderation.auto_check` — ModerationRequested: автопроверка объекта (§14.1, план 2.6).
- `moderation.rate_limit_signals` — раз в 15 минут: сигналы риска по систематическим 429
  (ARCHITECTURE §13.3).
"""

from dishka import FromDishka

from app.modules.moderation.application.ports import AUTO_CHECK
from app.modules.moderation.application.use_cases.auto_check import AutoCheck, AutoCheckCommand
from app.modules.moderation.application.use_cases.record_rate_limit_signals import (
    RecordRateLimitSignals,
    RecordRateLimitSignalsCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.platform.contracts.events.moderation import ModerationRequested
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber


@subscriber(ModerationRequested, AUTO_CHECK)
async def auto_check(event: ModerationRequested, check: FromDishka[AutoCheck]) -> None:
    await check(
        AutoCheckCommand(
            entity_type=EntityType(event.entity_type),
            entity_id=event.entity_id,
            author_id=event.author_id,
            edit=event.edit,
        )
    )


@periodic("moderation.rate_limit_signals", cron="4,19,34,49 * * * *")
async def rate_limit_signals(run: PeriodicRun) -> None:
    async with run.container() as request:
        record = await request.get(RecordRateLimitSignals)
        await record(RecordRateLimitSignalsCommand())
