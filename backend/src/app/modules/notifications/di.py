"""Сборка модуля notifications для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.notifications.application.ports import ChannelRepository
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
)
from app.modules.notifications.infrastructure.repositories import SqlChannelRepository


class NotificationsProvider(Provider):
    """Провайдер модуля notifications: связывает порты с реализациями."""

    scope = Scope.REQUEST

    channels = provide(SqlChannelRepository, provides=ChannelRepository)
    grant_telegram_write_access = provide(GrantTelegramWriteAccess)
