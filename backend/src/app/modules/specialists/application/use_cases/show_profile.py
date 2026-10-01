"""Вернуть скрытый профиль в каталог (POST /me/profile/show): санкция на публикацию — 403."""

from dataclasses import dataclass

from app.modules.identity.api import Action, IdentityApi
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.application.profiles import own_profile
from app.modules.specialists.domain.profile import Profile
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ShowProfileCommand:
    actor_id: UserId
    expected_version: int | None = None


class ShowProfile:
    def __init__(
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._profiles, self._identity, self._clock = uow, profiles, identity, clock

    async def __call__(self, cmd: ShowProfileCommand) -> Profile:
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id, cmd.expected_version)
            profile.show(now=self._clock.now())
            await self._profiles.save(profile)
        return profile
