"""«Подработка → Специалист» (POST /me/profile/become-pro): профиль в каталоге, но сначала —
снова проверка человеком (DEVELOPMENT_PLAN 2.8a)."""

from dataclasses import dataclass

from app.modules.identity.api import Action, IdentityApi
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.application.profiles import own_profile, request_review
from app.modules.specialists.domain.profile import Profile, ProfileStatus
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class BecomeProCommand:
    actor_id: UserId
    expected_version: int | None = None


class BecomePro:
    def __init__(
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._profiles, self._identity, self._clock = uow, profiles, identity, clock

    async def __call__(self, cmd: BecomeProCommand) -> Profile:
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        now = self._clock.now()
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id, cmd.expected_version)
            profile.become_pro(now=now)
            await self._profiles.save(profile)
            if profile.status is ProfileStatus.PENDING_REVIEW and profile.reviewed_kind:
                request_review(self._uow, profile, edit=False, now=now)
        return profile
