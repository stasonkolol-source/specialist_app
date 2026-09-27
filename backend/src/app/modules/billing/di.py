"""Сборка модуля billing для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class BillingProvider(Provider):
    """Провайдер модуля billing: связывает порты с реализациями."""

    scope = Scope.REQUEST
