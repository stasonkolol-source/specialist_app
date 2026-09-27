"""Сборка модуля catalog для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class CatalogProvider(Provider):
    """Провайдер модуля catalog: связывает порты с реализациями."""

    scope = Scope.REQUEST
