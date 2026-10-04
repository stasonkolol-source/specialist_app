"""Реализация SpecialistsApi (ADR-0020 §6): проверка профиля и работ портфолио для модерации,
профили для поиска."""

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
    WorkForReview,
)
from app.modules.specialists.application.ports import (
    PortfolioQuery,
    PortfolioRepository,
    ProfileQuery,
    ProfileRepository,
)
from app.modules.specialists.application.profiles import request_work_review
from app.modules.specialists.domain.portfolio import WorkStatus
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
        works: PortfolioRepository,
        catalog: CatalogApi,
        clock: Clock,
    ) -> None:
        self._uow, self._profiles, self._query = uow, profiles, query
        self._portfolio, self._works = portfolio, works
        self._catalog, self._clock = catalog, clock

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

    async def work_for_review(self, work_id: UUID) -> WorkForReview | None:
        item = await self._portfolio.get(work_id)
        if item is None or item.status is WorkStatus.REJECTED:
            return None
        found = await self._query.for_index([item.profile_id])
        if not found:
            return None
        profile = found[0]
        categories = await self._catalog.categories(profile.category_ids)
        return WorkForReview(
            user_id=profile.user_id,
            caption=item.caption,
            media_id=item.media_id,
            pending=item.pending,
            new_profile=profile.published_at is None,
            risk_level=max((int(c.risk_level) for c in categories), default=0),
        )

    async def approve_work(self, work_id: UUID) -> None:
        self._uow.require_active()
        item = await self._works.get_for_update(work_id)
        if item is not None and item.approve():
            await self._works.save(item)

    async def reject_work(self, work_id: UUID) -> None:
        self._uow.require_active()
        item = await self._works.get_for_update(work_id)
        if item is not None and item.reject():
            await self._works.save(item)

    async def recheck_works(self, media_id: MediaId) -> int:
        self._uow.require_active()
        waiting = [item for item in await self._portfolio.by_media([media_id]) if item.pending]
        if not waiting:
            return 0
        owners = {
            profile.id: profile.user_id
            for profile in await self._query.for_index({item.profile_id for item in waiting})
        }
        now = self._clock.now()
        requested = 0
        for item in waiting:
            if (owner := owners.get(item.profile_id)) is not None:
                request_work_review(self._uow, item, owner, now=now)
                requested += 1
        return requested
