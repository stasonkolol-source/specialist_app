"""Сборка модуля notifications для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.notifications.application.ports import (
    ChannelRepository,
    NotificationQuery,
    NotificationRenderer,
    NotificationRepository,
    RecipientData,
    SettingsRepository,
)
from app.modules.notifications.application.queries import NotificationQueries
from app.modules.notifications.application.use_cases.block_telegram_channel import (
    BlockTelegramChannel,
)
from app.modules.notifications.application.use_cases.expire_stale_deliveries import (
    ExpireStaleDeliveries,
)
from app.modules.notifications.application.use_cases.forget_recipient import ForgetRecipient
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
)
from app.modules.notifications.application.use_cases.mark_notifications_read import (
    MarkNotificationsRead,
)
from app.modules.notifications.application.use_cases.notify import Notify
from app.modules.notifications.application.use_cases.schedule_messages_notice import (
    ScheduleMessagesNotice,
)
from app.modules.notifications.application.use_cases.schedule_responses_notice import (
    ScheduleResponsesNotice,
)
from app.modules.notifications.application.use_cases.send_delivery import SendDelivery
from app.modules.notifications.application.use_cases.update_notification_settings import (
    UpdateNotificationSettings,
)
from app.modules.notifications.infrastructure.queries import SqlNotificationQuery
from app.modules.notifications.infrastructure.recipients import SqlRecipientData
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
    block_telegram_channel = provide(BlockTelegramChannel)
    expire_stale_deliveries = provide(ExpireStaleDeliveries)
    notify = provide(Notify)
    schedule_responses_notice = provide(ScheduleResponsesNotice)
    schedule_messages_notice = provide(ScheduleMessagesNotice)
    send_delivery = provide(SendDelivery)
    mark_read = provide(MarkNotificationsRead)
    update_settings = provide(UpdateNotificationSettings)
    recipients = provide(SqlRecipientData, provides=RecipientData)
    forget_recipient = provide(ForgetRecipient)

    @provide(scope=Scope.APP)
    def renderer(self, translator: Translator, telegram: TelegramSettings) -> NotificationRenderer:
        """Шаблоны читаются из каталогов процесса; кнопки ведут в Mini App окружения."""
        return GettextNotificationRenderer(translator, telegram.mini_app_url)
