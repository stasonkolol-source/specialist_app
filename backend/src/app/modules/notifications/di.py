"""Сборка модуля notifications для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class NotificationsProvider(Provider):
    """Провайдер модуля notifications: связывает порты с реализациями."""

    scope = Scope.REQUEST
