"""Сборка модуля reviews для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class ReviewsProvider(Provider):
    """Провайдер модуля reviews: связывает порты с реализациями."""

    scope = Scope.REQUEST
