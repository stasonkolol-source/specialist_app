"""Сборка модуля reviews для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.reviews.api import ReviewsApi
from app.modules.reviews.application.facade import ReviewsFacade
from app.modules.reviews.application.ports import (
    RatingStore,
    ReviewQueries,
    ReviewRepository,
    ReviewRequests,
)
from app.modules.reviews.application.use_cases.forget_user_reviews import ForgetUserReviews
from app.modules.reviews.application.use_cases.leave_review import LeaveReview
from app.modules.reviews.application.use_cases.list_my_reviews import ListMyReviews
from app.modules.reviews.application.use_cases.open_review_request import OpenReviewRequest
from app.modules.reviews.application.use_cases.recompute_rating import RecomputeRating
from app.modules.reviews.application.use_cases.recompute_ratings import RecomputeRatings
from app.modules.reviews.application.use_cases.remind_reviews import RemindReviews
from app.modules.reviews.application.use_cases.reply_to_review import ReplyToReview
from app.modules.reviews.infrastructure.aggregates import SqlRatingStore
from app.modules.reviews.infrastructure.queries import SqlReviewQueries
from app.modules.reviews.infrastructure.repositories import SqlReviewRepository
from app.modules.reviews.infrastructure.requests import SqlReviewRequests


class ReviewsProvider(Provider):
    """Провайдер модуля reviews: связывает порты с реализациями."""

    scope = Scope.REQUEST

    reviews = provide(SqlReviewRepository, provides=ReviewRepository)
    ratings = provide(SqlRatingStore, provides=RatingStore)
    queries = provide(SqlReviewQueries, provides=ReviewQueries)
    requests = provide(SqlReviewRequests, provides=ReviewRequests)
    facade = provide(ReviewsFacade, provides=ReviewsApi)
    """Фасад для карточки специалиста (BFF S08, S11), выдачи, сделки и модерации отзывов."""
    leave_review = provide(LeaveReview)
    reply_to_review = provide(ReplyToReview)
    list_my_reviews = provide(ListMyReviews)
    recompute_rating = provide(RecomputeRating)
    recompute_ratings = provide(RecomputeRatings)
    open_review_request = provide(OpenReviewRequest)
    remind_reviews = provide(RemindReviews)
    forget_user_reviews = provide(ForgetUserReviews)
