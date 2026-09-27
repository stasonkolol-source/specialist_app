"""Сборка модуля search для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class SearchProvider(Provider):
    """Провайдер модуля search: связывает порты с реализациями."""

    scope = Scope.REQUEST
