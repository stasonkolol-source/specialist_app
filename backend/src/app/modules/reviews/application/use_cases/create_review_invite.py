"""Ссылка-приглашение прошлому клиенту (POST /me/profile/review-invites, S55; DEVELOPMENT_PLAN
7.6а): только у опубликованного профиля — иначе ссылку некому открыть; не больше пяти занятых
мест (409 `review_invites_full`), считаются под advisory lock профиля."""

from dataclasses import dataclass

from app.modules.reviews.application.ports import ReviewInvites
from app.modules.reviews.domain.invite import ReviewInvite, new_token
from app.modules.reviews.errors import ReviewInvitesUnavailableError
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId

PUBLISHED = "published"
"""ProfileStatus, при котором ссылку можно открыть (S56)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateReviewInviteCommand:
    actor_id: UserId
    client_name: str | None = None


class CreateReviewInvite:
    def __init__(
        self, uow: UnitOfWork, invites: ReviewInvites, specialists: SpecialistsApi, clock: Clock
    ) -> None:
        self._uow, self._invites, self._specialists, self._clock = uow, invites, specialists, clock

    async def __call__(self, cmd: CreateReviewInviteCommand) -> ReviewInvite:
        profile = await self._specialists.profile_of(cmd.actor_id)
        if profile is None or profile.status != PUBLISHED:
            raise ReviewInvitesUnavailableError()
        async with self._uow:
            await self._invites.lock(profile.id)
            now = self._clock.now()
            taken = sum(
                invite.takes_slot(now) for invite in await self._invites.of_profile(profile.id)
            )
            invite = ReviewInvite.issue(
                token=new_token(),
                profile_id=profile.id,
                client_name=cmd.client_name,
                taken=taken,
                now=now,
            )
            await self._invites.add(invite)
        return invite
