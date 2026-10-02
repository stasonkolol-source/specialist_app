"""Сборка модуля reviews для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.reviews.api import ReviewsApi
from app.modules.reviews.application.facade import ReviewsFacade
from app.modules.reviews.application.ports import RatingAggregates
from app.modules.reviews.infrastructure.aggregates import SqlRatingAggregates


class ReviewsProvider(Provider):
    """Провайдер модуля reviews: связывает порты с реализациями."""

    scope = Scope.REQUEST

    aggregates = provide(SqlRatingAggregates, provides=RatingAggregates)
    facade = provide(ReviewsFacade, provides=ReviewsApi)
    """Фасад для карточки специалиста (BFF S08, S11) и выдачи."""
