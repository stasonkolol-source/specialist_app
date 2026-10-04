"""Задачи specialists (ADR-0020 §3).

- `specialists.reset_availability` — каждые 5 минут: снять «доступен сегодня» с истёкшим сроком.
- `specialists.forget_profile` — UserDeleted: профиль и портфолио удалённого аккаунта (§7.10).
- `specialists.stale_profile_reminders` — ежедневно в 11:00 по Белграду: давно не обновлённым
  профилям — ProfileStale, не чаще раза в 2 недели (5.7).
"""

from dishka import FromDishka

from app.modules.specialists.application.ports import FORGET_PROFILE
from app.modules.specialists.application.use_cases.forget_profile import (
    ForgetProfile,
    ForgetProfileCommand,
)
from app.modules.specialists.application.use_cases.remind_stale_profiles import (
    RemindStaleProfiles,
    RemindStaleProfilesCommand,
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


@periodic("specialists.stale_profile_reminders", cron="5 9,10 * * *")
async def stale_profile_reminders(run: PeriodicRun) -> None:
    """11:00 по Белграду — 09:00 UTC летом и 10:00 зимой: работает запуск, попавший в 11."""
    async with run.container() as request:
        remind = await request.get(RemindStaleProfiles)
        await remind(RemindStaleProfilesCommand())
