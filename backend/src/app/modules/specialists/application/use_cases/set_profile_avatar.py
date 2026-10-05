"""Фото профиля (S34, PUT /me/profile/avatar): загруженный файл с назначением avatar; null —
вернуть инициалы. Прежний файл удаляет media — задачей в той же транзакции."""

from dataclasses import dataclass

from app.modules.identity.api import Action, IdentityApi
from app.modules.media.api import MediaApi
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.application.profiles import own_profile, review_change
from app.modules.specialists.domain.profile import Profile
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import MediaId, UserId

AVATAR_PURPOSE = "avatar"


@dataclass(frozen=True, slots=True, kw_only=True)
class SetProfileAvatarCommand:
    actor_id: UserId
    media_id: MediaId | None
    expected_version: int | None = None


class SetProfileAvatar:
    def __init__(
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        media: MediaApi,
        clock: Clock,
        identity: IdentityApi,
    ) -> None:
        self._uow, self._profiles, self._media, self._clock = uow, profiles, media, clock
        self._identity = identity

    async def __call__(self, cmd: SetProfileAvatarCommand) -> Profile:
        # санкция на публикацию и галочка S02c — как у создания профиля (SEC-01)
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id, cmd.expected_version)
            if cmd.media_id is not None:
                await self._media.owned(cmd.actor_id, cmd.media_id, purpose=AVATAR_PURPOSE)
            previous = profile.avatar_media_id
            now = self._clock.now()
            if profile.set_avatar(cmd.media_id, now=now):
                await self._profiles.save(profile)
                review_change(self._uow, profile, ("avatar",), now=now)
                if previous is not None:
                    await self._media.discard(cmd.actor_id, previous)
        return profile
