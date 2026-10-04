"""Приглашения на «отзыв до платформы» (GET /me/profile/review-invites, S55; DEVELOPMENT_PLAN
7.6а): новые первыми, со статусом («Ждём отзыв», «На модерации», «Опубликован»…), именем того,
кто оставил отзыв, и сколько из пяти мест занято. Профиля нет — пустой список."""

from dataclasses import dataclass, field

from app.modules.identity.api import IdentityApi
from app.modules.reviews.application.dto import InviteListing
from app.modules.reviews.application.ports import ReviewInvites
from app.modules.reviews.domain.invite import InviteStatus, ReviewInvite
from app.modules.specialists.api import SpecialistsApi
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ListReviewInvitesCommand:
    actor_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class InviteItem:
    listing: InviteListing
    status: InviteStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewInvitesPage:
    items: list[InviteItem] = field(default_factory=list)
    taken: int = 0
    """Занятых мест из пяти: «4 из 5 · осталось 1»."""
    names: dict[UserId, str] = field(default_factory=dict)
    """Кто оставил отзыв; аккаунт удалён — нет в словаре."""


class ListReviewInvites:
    def __init__(
        self,
        invites: ReviewInvites,
        specialists: SpecialistsApi,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._invites, self._specialists = invites, specialists
        self._identity, self._clock = identity, clock

    async def __call__(self, cmd: ListReviewInvitesCommand) -> ReviewInvitesPage:
        profile = await self._specialists.profile_of(cmd.actor_id)
        if profile is None:
            return ReviewInvitesPage()
        found = await self._invites.listing(profile.id)
        now = self._clock.now()
        items: list[InviteItem] = []
        taken = 0
        for listing in found:
            invite = ReviewInvite(
                token=listing.token,
                profile_id=profile.id,
                client_name=listing.client_name,
                created_at=listing.created_at,
                expires_at=listing.expires_at,
                used_by=listing.used_by,
                used_at=listing.used_at,
                review_id=listing.review_id,
            )
            taken += invite.takes_slot(now)
            items.append(
                InviteItem(listing=listing, status=invite.status(listing.review_status, now))
            )
        users = await self._identity.users({i.used_by for i in found if i.used_by is not None})
        return ReviewInvitesPage(
            items=items,
            taken=taken,
            names={user_id: u.display_name for user_id, u in users.items() if not u.is_deleted},
        )
