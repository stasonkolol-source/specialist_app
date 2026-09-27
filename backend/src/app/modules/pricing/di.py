"""Сборка модуля pricing для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class PricingProvider(Provider):
    """Провайдер модуля pricing: связывает порты с реализациями."""

    scope = Scope.REQUEST
