"""Сборка модуля geo для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class GeoProvider(Provider):
    """Провайдер модуля geo: связывает порты с реализациями."""

    scope = Scope.REQUEST
