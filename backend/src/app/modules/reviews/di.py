"""Сборка модуля reviews для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.reviews.api import ReviewsApi
from app.modules.reviews.application.facade import ReviewsFacade
from app.modules.reviews.application.ports import RatingStore, ReviewQueries, ReviewRepository
from app.modules.reviews.application.use_cases.leave_review import LeaveReview
from app.modules.reviews.application.use_cases.list_my_reviews import ListMyReviews
from app.modules.reviews.application.use_cases.recompute_rating import RecomputeRating
from app.modules.reviews.application.use_cases.reply_to_review import ReplyToReview
from app.modules.reviews.infrastructure.aggregates import SqlRatingStore
from app.modules.reviews.infrastructure.queries import SqlReviewQueries
from app.modules.reviews.infrastructure.repositories import SqlReviewRepository


class ReviewsProvider(Provider):
    """Провайдер модуля reviews: связывает порты с реализациями."""

    scope = Scope.REQUEST

    reviews = provide(SqlReviewRepository, provides=ReviewRepository)
    ratings = provide(SqlRatingStore, provides=RatingStore)
    queries = provide(SqlReviewQueries, provides=ReviewQueries)
    facade = provide(ReviewsFacade, provides=ReviewsApi)
    """Фасад для карточки специалиста (BFF S08, S11), выдачи, сделки и модерации отзывов."""
    leave_review = provide(LeaveReview)
    reply_to_review = provide(ReplyToReview)
    list_my_reviews = provide(ListMyReviews)
    recompute_rating = provide(RecomputeRating)
