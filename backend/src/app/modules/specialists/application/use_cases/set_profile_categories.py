"""Категории профиля целиком (PUT /me/profile/categories): первая — основная. Категория должна
быть в справочнике, включена и не запрещена для профилей (catalog)."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.catalog.api import CatalogApi
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.application.profiles import allowed_categories, own_profile
from app.modules.specialists.domain.profile import Profile
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CategoryId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class SetProfileCategoriesCommand:
    actor_id: UserId
    category_ids: Sequence[CategoryId]
    expected_version: int | None = None


class SetProfileCategories:
    def __init__(
        self, uow: UnitOfWork, profiles: ProfileRepository, catalog: CatalogApi, clock: Clock
    ) -> None:
        self._uow, self._profiles, self._catalog, self._clock = uow, profiles, catalog, clock

    async def __call__(self, cmd: SetProfileCategoriesCommand) -> Profile:
        ids = await allowed_categories(self._catalog, cmd.category_ids)
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id, cmd.expected_version)
            profile.set_categories(ids, now=self._clock.now())
            await self._profiles.save(profile)
        return profile
