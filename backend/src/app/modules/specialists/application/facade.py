"""Реализация SpecialistsApi для модерации (ADR-0020 §6): проверка профиля через адаптер цели."""

from uuid import UUID

from app.modules.catalog.api import CatalogApi
from app.modules.specialists.api import ProfileForReview, SpecialistsApi
from app.modules.specialists.application.ports import ProfileRepository
from app.modules.specialists.domain.profile import ProfileId, ProfileStatus
from app.modules.specialists.errors import ProfileNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

REVIEWABLE = frozenset(
    {ProfileStatus.PENDING_REVIEW, ProfileStatus.PUBLISHED, ProfileStatus.HIDDEN}
)


class SpecialistsFacade(SpecialistsApi):
    def __init__(
        self, uow: UnitOfWork, profiles: ProfileRepository, catalog: CatalogApi, clock: Clock
    ) -> None:
        self._uow, self._profiles, self._catalog, self._clock = uow, profiles, catalog, clock

    async def profile_for_review(self, profile_id: UUID) -> ProfileForReview | None:
        async with self._uow:
            try:
                profile = await self._profiles.get_for_update(ProfileId(profile_id))
            except ProfileNotFoundError:
                return None
        if profile.status not in REVIEWABLE:
            return None
        categories = await self._catalog.categories(profile.category_ids)
        text = "\n".join(
            part for part in (profile.display_name, profile.headline, profile.about) if part
        )
        return ProfileForReview(
            user_id=profile.user_id,
            text=text,
            version=profile.version,
            first_review=profile.first_review,
            risk_level=max((int(c.risk_level) for c in categories), default=0),
        )

    async def approve_profile(self, profile_id: UUID, *, version: int | None) -> None:
        self._uow.require_active()
        try:
            profile = await self._profiles.get_for_update(ProfileId(profile_id))
        except ProfileNotFoundError:
            return
        if profile.approve(now=self._clock.now(), version=version):
            await self._profiles.save(profile)

    async def reject_profile(self, profile_id: UUID, *, reason_code: str) -> None:
        self._uow.require_active()
        try:
            profile = await self._profiles.get_for_update(ProfileId(profile_id))
        except ProfileNotFoundError:
            return
        profile.reject(reason_code=reason_code, now=self._clock.now())
        await self._profiles.save(profile)
