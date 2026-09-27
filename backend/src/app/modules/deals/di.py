"""Сборка модуля deals для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class DealsProvider(Provider):
    """Провайдер модуля deals: связывает порты с реализациями."""

    scope = Scope.REQUEST
