"""«Доступен сегодня до …» (S38, PUT /me/profile/availability, `/available` в боте)."""

from dataclasses import dataclass
from datetime import time

from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.application.profiles import own_profile
from app.modules.specialists.domain.profile import Profile
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class SetAvailabilityCommand:
    actor_id: UserId
    until: time | None
    """Время по Белграду, сегодня; None — выключить."""
    expected_version: int | None = None


class SetAvailability:
    def __init__(self, uow: UnitOfWork, profiles: ProfileRepository, clock: Clock) -> None:
        self._uow, self._profiles, self._clock = uow, profiles, clock

    async def __call__(self, cmd: SetAvailabilityCommand) -> Profile:
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id, cmd.expected_version)
            if profile.set_availability(cmd.until, now=self._clock.now()):
                await self._profiles.save(profile)
        return profile
