"""Районы выезда целиком (PUT /me/profile/areas): районы города профиля (geo). База и публичная
точка — центр первого района: точного адреса мастер S32c не спрашивает."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.geo.api import GeoApi
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.application.profiles import allowed_areas, own_profile
from app.modules.specialists.domain.profile import Profile
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DistrictId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class SetProfileAreasCommand:
    actor_id: UserId
    district_ids: Sequence[DistrictId]
    expected_version: int | None = None


class SetProfileAreas:
    def __init__(
        self, uow: UnitOfWork, profiles: ProfileRepository, geo: GeoApi, clock: Clock
    ) -> None:
        self._uow, self._profiles, self._geo, self._clock = uow, profiles, geo, clock

    async def __call__(self, cmd: SetProfileAreasCommand) -> Profile:
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id, cmd.expected_version)
            ids, base = await allowed_areas(self._geo, profile.city_id, cmd.district_ids)
            profile.set_areas(ids, base=base, public=base, now=self._clock.now())
            await self._profiles.save(profile)
        return profile
