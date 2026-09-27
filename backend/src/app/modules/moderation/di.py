"""Сборка модуля moderation для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope


class ModerationProvider(Provider):
    """Провайдер модуля moderation: связывает порты с реализациями."""

    scope = Scope.REQUEST
