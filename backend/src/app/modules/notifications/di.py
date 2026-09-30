"""Сборка модуля notifications для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.notifications.application.ports import (
    ChannelRepository,
    NotificationQuery,
    NotificationRenderer,
    NotificationRepository,
    SettingsRepository,
)
from app.modules.notifications.application.queries import NotificationQueries
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
)
from app.modules.notifications.application.use_cases.mark_notifications_read import (
    MarkNotificationsRead,
)
from app.modules.notifications.application.use_cases.notify import Notify
from app.modules.notifications.application.use_cases.send_delivery import SendDelivery
from app.modules.notifications.application.use_cases.update_notification_settings import (
    UpdateNotificationSettings,
)
from app.modules.notifications.infrastructure.queries import SqlNotificationQuery
from app.modules.notifications.infrastructure.rendering import GettextNotificationRenderer
from app.modules.notifications.infrastructure.repositories import (
    SqlChannelRepository,
    SqlNotificationRepository,
    SqlSettingsRepository,
)
from app.platform.i18n.translator import Translator
from app.platform.settings import TelegramSettings


class NotificationsProvider(Provider):
    """Провайдер модуля notifications: связывает порты с реализациями."""

    scope = Scope.REQUEST

    channels = provide(SqlChannelRepository, provides=ChannelRepository)
    notifications = provide(SqlNotificationRepository, provides=NotificationRepository)
    settings = provide(SqlSettingsRepository, provides=SettingsRepository)
    query = provide(SqlNotificationQuery, provides=NotificationQuery)
    queries = provide(NotificationQueries)

    grant_telegram_write_access = provide(GrantTelegramWriteAccess)
    notify = provide(Notify)
    send_delivery = provide(SendDelivery)
    mark_read = provide(MarkNotificationsRead)
    update_settings = provide(UpdateNotificationSettings)

    @provide(scope=Scope.APP)
    def renderer(self, translator: Translator, telegram: TelegramSettings) -> NotificationRenderer:
        """Шаблоны читаются из каталогов процесса; кнопки ведут в Mini App окружения."""
        return GettextNotificationRenderer(translator, telegram.mini_app_url)
