"""Сборка модуля messaging для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class MessagingProvider(Provider):
    """Провайдер модуля messaging: связывает порты с реализациями."""

    scope = Scope.REQUEST
