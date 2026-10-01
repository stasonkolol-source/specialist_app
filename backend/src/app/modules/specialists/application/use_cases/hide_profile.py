"""Скрыть опубликованный профиль из каталога (POST /me/profile/hide)."""

from dataclasses import dataclass

from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.application.profiles import own_profile
from app.modules.specialists.domain.profile import Profile
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class HideProfileCommand:
    actor_id: UserId
    expected_version: int | None = None


class HideProfile:
    def __init__(
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        clock: Clock,
    ) -> None:
        self._uow, self._profiles, self._clock = uow, profiles, clock

    async def __call__(self, cmd: HideProfileCommand) -> Profile:
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id, cmd.expected_version)
            profile.hide(now=self._clock.now())
            await self._profiles.save(profile)
        return profile
