"""Задачи specialists (ADR-0020 §3).

- `specialists.reset_availability` — каждые 5 минут: снять «доступен сегодня» с истёкшим сроком.
- `specialists.forget_profile` — UserDeleted: профиль и портфолио удалённого аккаунта (§7.10).
"""

from dishka import FromDishka

from app.modules.specialists.application.ports import FORGET_PROFILE
from app.modules.specialists.application.use_cases.forget_profile import (
    ForgetProfile,
    ForgetProfileCommand,
)
from app.modules.specialists.application.use_cases.reset_availability import (
    ResetAvailability,
    ResetAvailabilityCommand,
)
from app.platform.contracts.events.identity import UserDeleted
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber


@periodic("specialists.reset_availability", cron="*/5 * * * *")
async def reset_availability(run: PeriodicRun) -> None:
    async with run.container() as request:
        reset = await request.get(ResetAvailability)
        await reset(ResetAvailabilityCommand())


@subscriber(UserDeleted, FORGET_PROFILE)
async def forget_profile(event: UserDeleted, forget: FromDishka[ForgetProfile]) -> None:
    await forget(ForgetProfileCommand(user_id=event.user_id))
