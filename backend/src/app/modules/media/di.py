"""Сборка модуля media для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class MediaProvider(Provider):
    """Провайдер модуля media: связывает порты с реализациями."""

    scope = Scope.REQUEST
