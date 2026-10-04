"""Отозвать ссылку-приглашение (DELETE /me/profile/review-invites/{token}, S55; DEVELOPMENT_PLAN
7.6а): только свою и только неиспользованную — по использованной уже есть отзыв (409
`review_invite_used`). Чужая и несуществующая — одинаково 404. Место освобождается."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.reviews.application.ports import ReviewInvites
from app.modules.reviews.errors import ReviewInviteNotFoundError, ReviewInviteUsedError
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class RevokeReviewInviteCommand:
    actor_id: UserId
    token: UUID


class RevokeReviewInvite:
    def __init__(
        self, uow: UnitOfWork, invites: ReviewInvites, specialists: SpecialistsApi
    ) -> None:
        self._uow, self._invites, self._specialists = uow, invites, specialists

    async def __call__(self, cmd: RevokeReviewInviteCommand) -> None:
        profile = await self._specialists.profile_of(cmd.actor_id)
        async with self._uow:
            invite = await self._invites.find_for_update(cmd.token)
            if invite is None or profile is None or invite.profile_id != profile.id:
                raise ReviewInviteNotFoundError()
            if invite.used:
                raise ReviewInviteUsedError()
            await self._invites.remove(cmd.token)
