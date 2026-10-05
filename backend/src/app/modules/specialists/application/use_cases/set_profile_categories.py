"""Категории профиля целиком (PUT /me/profile/categories): первая — основная. Категория должна
быть в справочнике, включена и не запрещена для профилей (catalog)."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.catalog.api import CatalogApi
from app.modules.identity.api import Action, IdentityApi
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.application.profiles import (
    allowed_categories,
    own_profile,
    review_change,
)
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
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        catalog: CatalogApi,
        clock: Clock,
        identity: IdentityApi,
    ) -> None:
        self._uow, self._profiles, self._catalog, self._clock = uow, profiles, catalog, clock
        self._identity = identity

    async def __call__(self, cmd: SetProfileCategoriesCommand) -> Profile:
        # санкция на публикацию и галочка S02c — как у создания профиля (SEC-01)
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        ids = await allowed_categories(self._catalog, cmd.category_ids)
        now = self._clock.now()
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id, cmd.expected_version)
            changed = profile.set_categories(ids, now=now)
            await self._profiles.save(profile)
            review_change(self._uow, profile, ("category_ids",) if changed else (), now=now)
        return profile
