"""Снять «доступен сегодня» с истёкшим сроком (`specialists.reset_availability`, каждые 5 минут):
по пачкам, каждая — своей транзакцией; занятые другими профили — в следующий раз."""

from dataclasses import dataclass
from typing import Final

from app.modules.specialists.application.ports import ProfileRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

CHUNK: Final = 100


@dataclass(frozen=True, slots=True, kw_only=True)
class ResetAvailabilityCommand:
    limit: int = 10_000
    """Сколько профилей за один запуск, не больше: остальное — через 5 минут."""


class ResetAvailability:
    def __init__(self, uow: UnitOfWork, profiles: ProfileRepository, clock: Clock) -> None:
        self._uow, self._profiles, self._clock = uow, profiles, clock

    async def __call__(self, cmd: ResetAvailabilityCommand) -> int:
        """Сколько профилей больше не «доступны сегодня»."""
        now = self._clock.now()
        checked = reset = 0
        while checked < cmd.limit:
            chunk = min(CHUNK, cmd.limit - checked)
            async with self._uow:
                expired = await self._profiles.expired_availability(now, limit=chunk)
                for profile_id in expired:
                    profile = await self._profiles.get_for_update(profile_id)
                    if profile.expire_availability(now=now):
                        await self._profiles.save(profile)
                        reset += 1
            checked += len(expired)
            if len(expired) < chunk:
                break
        return reset
