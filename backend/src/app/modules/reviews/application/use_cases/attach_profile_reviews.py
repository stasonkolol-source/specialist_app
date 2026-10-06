"""Привязать к профилю отзывы, оставленные до него (подписчик ProfilePublished; UXM-12).

Сделка запоминает профиль исполнителя только опубликованный, и отзыв берёт его из сделки. Кто
откликался и работал, пока профиль ждал проверки (или профиля не было вовсе), получал отзывы без
профиля: на карточке — «Новый специалист», без оценки. Когда профиль опубликован, такие отзывы
переходят к нему, и рейтинг профиля пересчитывается. Повтор события ничего не меняет.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.reviews.application.ports import ReviewRepository
from app.modules.reviews.application.use_cases.recompute_rating import (
    RecomputeRating,
    RecomputeRatingCommand,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class AttachProfileReviewsCommand:
    user_id: UserId
    profile_id: UUID


class AttachProfileReviews:
    def __init__(
        self, uow: UnitOfWork, reviews: ReviewRepository, recompute: RecomputeRating
    ) -> None:
        self._uow, self._reviews, self._recompute = uow, reviews, recompute

    async def __call__(self, cmd: AttachProfileReviewsCommand) -> int:
        """Сколько отзывов привязано."""
        async with self._uow:
            attached = await self._reviews.attach_profile(cmd.user_id, cmd.profile_id)
        if attached:
            # пересчёт — своей транзакцией под advisory lock профиля и видит привязанные
            await self._recompute(RecomputeRatingCommand(profile_id=cmd.profile_id))
        return attached
