"""Сборка модуля growth для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class GrowthProvider(Provider):
    """Провайдер модуля growth: связывает порты с реализациями."""

    scope = Scope.REQUEST
