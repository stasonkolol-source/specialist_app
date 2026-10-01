"""Задачи specialists (ADR-0020 §3).

- `specialists.reset_availability` — каждые 5 минут: снять «доступен сегодня» с истёкшим сроком.
"""

from app.modules.specialists.application.use_cases.reset_availability import (
    ResetAvailability,
    ResetAvailabilityCommand,
)
from app.platform.queue.tasks import PeriodicRun, periodic


@periodic("specialists.reset_availability", cron="*/5 * * * *")
async def reset_availability(run: PeriodicRun) -> None:
    async with run.container() as request:
        reset = await request.get(ResetAvailability)
        await reset(ResetAvailabilityCommand())
