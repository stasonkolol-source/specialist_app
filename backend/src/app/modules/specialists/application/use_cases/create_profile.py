"""Начать профиль исполнителя (S32a, POST /me/profile): «Специалист» или «Подработка» —
черновик. Создающее действие: санкция или непринятые правила — 403; один профиль на человека."""

from dataclasses import dataclass

from app.modules.geo.api import GeoApi
from app.modules.identity.api import Action, IdentityApi
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.domain.profile import Profile, ProfileKind
from app.modules.specialists.errors import InvalidProfileError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CityId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateProfileCommand:
    actor_id: UserId
    kind: ProfileKind
    city_id: CityId
    display_name: str | None = None
    """Пусто — имя из Telegram (identity)."""


class CreateProfile:
    def __init__(
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        identity: IdentityApi,
        geo: GeoApi,
        clock: Clock,
    ) -> None:
        self._uow, self._profiles, self._identity = uow, profiles, identity
        self._geo, self._clock = geo, clock

    async def __call__(self, cmd: CreateProfileCommand) -> Profile:
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        city = await self._geo.city(cmd.city_id)
        if city is None or not city.is_active:
            raise InvalidProfileError(field="city_id")
        name = cmd.display_name
        if not name:
            user = await self._identity.get_user(cmd.actor_id)
            name = user.display_name if user is not None else ""
        async with self._uow:
            profile = Profile.create(
                user_id=cmd.actor_id,
                kind=cmd.kind,
                display_name=name,
                city_id=cmd.city_id,
                now=self._clock.now(),
            )
            await self._profiles.add(profile)
        return profile
