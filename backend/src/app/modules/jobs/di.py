"""Сборка модуля jobs для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class JobsProvider(Provider):
    """Провайдер модуля jobs: связывает порты с реализациями."""

    scope = Scope.REQUEST
