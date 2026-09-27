"""Сборка модуля specialists для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class SpecialistsProvider(Provider):
    """Провайдер модуля specialists: связывает порты с реализациями."""

    scope = Scope.REQUEST
