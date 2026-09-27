"""Сборка модуля identity для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class IdentityProvider(Provider):
    """Провайдер модуля identity: связывает порты с реализациями."""

    scope = Scope.REQUEST
