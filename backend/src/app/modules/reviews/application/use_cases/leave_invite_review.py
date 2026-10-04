"""«Отзыв до платформы» по ссылке-приглашению (POST /review-invites/{token}, S56; DEVELOPMENT_PLAN
7.6а; ADR-0016): прошлый клиент входит через Telegram и оставляет оценку, «что делал мастер» и
текст — те же правила, что у отзыва по сделке, без критериев. Ссылка — одна на отзыв:
отозванная, истёкшая, использованная и несуществующая — одинаково 404, как и ссылка профиля,
которого не видно в каталоге. Себя не оценить (409 `own_profile_review`), второй отзыв о том
же специалисте — 409 `pre_platform_review_exists`. Отзыв ждёт модератора (ModerationRequested
→ цель `review`, `always_review`), на карточке — с отдельной меткой и в рейтинг не входит."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.api import Action, IdentityApi
from app.modules.reviews.application.ports import ReviewInvites, ReviewRepository
from app.modules.reviews.application.use_cases.leave_review import REVIEW
from app.modules.reviews.domain.review import Review, ReviewId
from app.modules.reviews.errors import ReviewInviteNotFoundError
from app.modules.specialists.api import SpecialistsApi
from app.platform.contracts.events.moderation import ModerationRequested
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId, new_id


@dataclass(frozen=True, slots=True, kw_only=True)
class LeaveInviteReviewCommand:
    actor_id: UserId
    token: UUID
    rating: int
    work_title: str | None = None
    body: str | None = None


class LeaveInviteReview:
    def __init__(
        self,
        uow: UnitOfWork,
        reviews: ReviewRepository,
        invites: ReviewInvites,
        specialists: SpecialistsApi,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._reviews, self._invites = uow, reviews, invites
        self._specialists, self._identity, self._clock = specialists, identity, clock

    async def __call__(self, cmd: LeaveInviteReviewCommand) -> Review:
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        async with self._uow:
            invite = await self._invites.find_for_update(cmd.token)
            now = self._clock.now()
            if invite is None or not invite.usable(now):
                raise ReviewInviteNotFoundError()
            profile = await self._specialists.public_profile(invite.profile_id)
            if profile is None or await self._identity.hidden_from_search([profile.user_id]):
                raise ReviewInviteNotFoundError()
            review = Review.pre_platform(
                review_id=ReviewId(new_id()),
                author_id=cmd.actor_id,
                subject_user_id=profile.user_id,
                subject_profile_id=profile.id,
                rating=cmd.rating,
                work_title=cmd.work_title,
                body=cmd.body,
                now=now,
            )
            await self._reviews.add(review)
            invite.use(by=cmd.actor_id, review_id=review.id, now=now)
            await self._invites.mark_used(invite)
            self._uow.add_event(
                ModerationRequested(
                    entity_type=REVIEW,
                    entity_id=review.id,
                    author_id=review.author_id,
                    occurred_at=review.created_at,
                )
            )
        return review
