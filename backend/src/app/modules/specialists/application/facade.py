"""Реализация SpecialistsApi (ADR-0020 §6): проверка профиля для модерации, профили для поиска."""

from collections.abc import Collection
from uuid import UUID

from app.modules.catalog.api import CatalogApi
from app.modules.specialists.api import (
    PortfolioWorkRef,
    ProfileForIndex,
    ProfileForReview,
    ProfileRef,
    PublicCard,
    PublicProfile,
    SpecialistsApi,
)
from app.modules.specialists.application.ports import (
    PortfolioQuery,
    ProfileQuery,
    ProfileRepository,
)
from app.modules.specialists.domain.profile import ProfileId, ProfileStatus
from app.modules.specialists.errors import ProfileNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import MediaId, UserId

REVIEWABLE = frozenset(
    {ProfileStatus.PENDING_REVIEW, ProfileStatus.PUBLISHED, ProfileStatus.HIDDEN}
)


class SpecialistsFacade(SpecialistsApi):
    def __init__(
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        query: ProfileQuery,
        portfolio: PortfolioQuery,
        catalog: CatalogApi,
        clock: Clock,
    ) -> None:
        self._uow, self._profiles, self._query = uow, profiles, query
        self._portfolio, self._catalog, self._clock = portfolio, catalog, clock

    async def profile_of(self, user_id: UserId) -> ProfileRef | None:
        view = await self._query.of_user(user_id)
        if view is None:
            return None
        return ProfileRef(id=view.id, kind=view.kind.value, status=view.status.value)

    async def profiles_of(self, user_ids: Collection[UserId]) -> dict[UserId, ProfileRef]:
        return await self._query.refs_of_users(user_ids)

    async def profiles_for_index(self, profile_ids: Collection[UUID]) -> list[ProfileForIndex]:
        return await self._query.for_index(profile_ids)

    async def public_profile(self, profile_id: UUID) -> PublicProfile | None:
        return await self._query.public(profile_id)

    async def public_cards(self, profile_ids: Collection[UUID]) -> dict[UUID, PublicCard]:
        return await self._query.public_cards(profile_ids) if profile_ids else {}

    async def published_profile_ids(self, *, after: UUID | None, limit: int) -> list[UUID]:
        return await self._query.published_ids(after=after, limit=limit)

    async def works_by_media(
        self, media_ids: Collection[MediaId]
    ) -> dict[MediaId, PortfolioWorkRef]:
        return {
            item.media_id: PortfolioWorkRef(
                id=item.id, profile_id=item.profile_id, status=item.status.value
            )
            for item in await self._portfolio.by_media(media_ids)
        }

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
