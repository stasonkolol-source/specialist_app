"""Поля профиля (S32a–c, S34; PATCH /me/profile). Правки опубликованного применяются сразу,
изменённый текст уходит на пост-модерацию (§7.9); правка ждущего первой проверки — снова на
проверку (ADV-11). Тип меняется только у черновика."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.identity.api import Action, IdentityApi
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.application.profiles import own_profile, review_change
from app.modules.specialists.domain.profile import Profile, ProfileKind
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class EditProfileCommand:
    actor_id: UserId
    expected_version: int | None = None
    kind: str | None = None
    display_name: str | None = None
    headline: str | None = None
    """Пустая строка — очистить."""
    about: str | None = None
    languages: Sequence[str] | None = None
    travel_radius_km: int | None = None
    work_modes: Sequence[str] | None = None


class EditProfile:
    def __init__(
        self, uow: UnitOfWork, profiles: ProfileRepository, clock: Clock, identity: IdentityApi
    ) -> None:
        self._uow, self._profiles, self._clock = uow, profiles, clock
        self._identity = identity

    async def __call__(self, cmd: EditProfileCommand) -> Profile:
        # санкция на публикацию и галочка S02c — как у создания профиля (SEC-01)
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        now = self._clock.now()
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id, cmd.expected_version)
            if cmd.kind is not None:
                profile.change_kind(ProfileKind(cmd.kind))
            changed = profile.edit(
                now=now,
                display_name=cmd.display_name,
                headline=cmd.headline,
                about=cmd.about,
                languages=cmd.languages,
                travel_radius_km=cmd.travel_radius_km,
                work_modes=cmd.work_modes,
            )
            await self._profiles.save(profile)
            review_change(self._uow, profile, changed, now=now)
        return profile
