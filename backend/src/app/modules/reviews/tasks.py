"""Задачи reviews (ADR-0020 §3).

- `reviews.recompute_on_published` — ReviewPublished: пересчитать рейтинг профиля; изменился —
  RatingChanged, поиск обновит выдачу (DEVELOPMENT_PLAN 7.2);
- `reviews.recompute_on_removed` — ReviewRemoved: то же после снятия опубликованного отзыва.
- `reviews.open_request` — DealCompleted: клиенту `review.request` (через ReviewRequested).
- `reviews.reminders` — раз в час: напомнить через сутки и за 2 дня до конца окна в 14 дней.
- `reviews.recompute_ratings` — ночью: пересчёт всех рейтингов (затухание, средние категорий).
- `reviews.forget_user` — UserDeleted: отзывы и ответы удалённого аккаунта стираются.
"""

from uuid import UUID

from dishka import FromDishka

from app.modules.reviews.application.ports import (
    FORGET_USER,
    OPEN_REQUEST,
    RECOMPUTE_ON_PUBLISHED,
    RECOMPUTE_ON_REMOVED,
)
from app.modules.reviews.application.use_cases.forget_user_reviews import (
    ForgetUserReviews,
    ForgetUserReviewsCommand,
)
from app.modules.reviews.application.use_cases.open_review_request import (
    OpenReviewRequest,
    OpenReviewRequestCommand,
)
from app.modules.reviews.application.use_cases.recompute_rating import (
    RecomputeRating,
    RecomputeRatingCommand,
)
from app.modules.reviews.application.use_cases.recompute_ratings import (
    RecomputeRatings,
    RecomputeRatingsCommand,
)
from app.modules.reviews.application.use_cases.remind_reviews import (
    RemindReviews,
    RemindReviewsCommand,
)
from app.platform.contracts.events.deals import DealCompleted
from app.platform.contracts.events.identity import UserDeleted
from app.platform.contracts.events.reviews import ReviewPublished, ReviewRemoved
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber


async def _recompute(recompute: RecomputeRating, profile_id: UUID | None) -> None:
    if profile_id is not None:
        await recompute(RecomputeRatingCommand(profile_id=profile_id))


@subscriber(ReviewPublished, RECOMPUTE_ON_PUBLISHED)
async def recompute_on_published(
    event: ReviewPublished, recompute: FromDishka[RecomputeRating]
) -> None:
    await _recompute(recompute, event.subject_profile_id)


@subscriber(ReviewRemoved, RECOMPUTE_ON_REMOVED)
async def recompute_on_removed(
    event: ReviewRemoved, recompute: FromDishka[RecomputeRating]
) -> None:
    await _recompute(recompute, event.subject_profile_id)


@subscriber(DealCompleted, OPEN_REQUEST)
async def open_request(event: DealCompleted, open_: FromDishka[OpenReviewRequest]) -> None:
    await open_(
        OpenReviewRequestCommand(
            deal_id=event.deal_id,
            client_id=event.client_id,
            performer_id=event.performer_id,
            completed_at=event.occurred_at,
        )
    )


@periodic("reviews.reminders", cron="17 * * * *")
async def reminders(run: PeriodicRun) -> None:
    async with run.container() as request:
        await (await request.get(RemindReviews))(RemindReviewsCommand())


@periodic("reviews.recompute_ratings", cron="5 3 * * *")
async def recompute_ratings(run: PeriodicRun) -> None:
    async with run.container() as request:
        await (await request.get(RecomputeRatings))(RecomputeRatingsCommand())


@subscriber(UserDeleted, FORGET_USER)
async def forget_user(event: UserDeleted, forget: FromDishka[ForgetUserReviews]) -> None:
    await forget(ForgetUserReviewsCommand(user_id=event.user_id))
