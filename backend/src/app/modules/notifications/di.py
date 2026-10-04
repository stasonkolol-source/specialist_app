"""Сборка модуля notifications для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.jobs.api import DigestSchedule
from app.modules.notifications.application.ports import (
    AudienceSource,
    BroadcastQuery,
    BroadcastRepository,
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
from app.modules.notifications.application.use_cases.cancel_broadcast import CancelBroadcast
from app.modules.notifications.application.use_cases.create_broadcast import CreateBroadcast
from app.modules.notifications.application.use_cases.expire_stale_deliveries import (
    ExpireStaleDeliveries,
)
from app.modules.notifications.application.use_cases.fan_out_broadcast import FanOutBroadcast
from app.modules.notifications.application.use_cases.finish_broadcast import FinishBroadcast
from app.modules.notifications.application.use_cases.forget_recipient import ForgetRecipient
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
)
from app.modules.notifications.application.use_cases.mark_notifications_read import (
    MarkNotificationsRead,
)
from app.modules.notifications.application.use_cases.notify import Notify
from app.modules.notifications.application.use_cases.retire_card import RetireCard
from app.modules.notifications.application.use_cases.retire_job_cards import RetireJobCards
from app.modules.notifications.application.use_cases.schedule_messages_notice import (
    ScheduleMessagesNotice,
)
from app.modules.notifications.application.use_cases.schedule_responses_notice import (
    ScheduleResponsesNotice,
)
from app.modules.notifications.application.use_cases.send_broadcast_test import (
    SendBroadcastTest,
)
from app.modules.notifications.application.use_cases.send_delivery import SendDelivery
from app.modules.notifications.application.use_cases.start_broadcast import StartBroadcast
from app.modules.notifications.application.use_cases.toggle_bot_setting import ToggleBotSetting
from app.modules.notifications.application.use_cases.update_notification_settings import (
    UpdateNotificationSettings,
)
from app.modules.notifications.infrastructure.broadcasts import (
    FacadeAudienceSource,
    SqlBroadcastQuery,
    SqlBroadcastRepository,
)
from app.modules.notifications.infrastructure.digest_schedule import SettingsDigestSchedule
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
    toggle_bot_setting = provide(ToggleBotSetting)
    recipients = provide(SqlRecipientData, provides=RecipientData)
    forget_recipient = provide(ForgetRecipient)
    retire_job_cards = provide(RetireJobCards)
    retire_card = provide(RetireCard)
    digest_schedule = provide(SettingsDigestSchedule, provides=DigestSchedule)
    """Когда кому подборка заявок по подпискам (jobs.alert_digests, 5.7)."""

    # рассылки из админки (2.7b)
    broadcasts = provide(SqlBroadcastRepository, provides=BroadcastRepository)
    broadcast_query = provide(SqlBroadcastQuery, provides=BroadcastQuery)
    audience = provide(FacadeAudienceSource, provides=AudienceSource)
    create_broadcast = provide(CreateBroadcast)
    start_broadcast = provide(StartBroadcast)
    cancel_broadcast = provide(CancelBroadcast)
    send_broadcast_test = provide(SendBroadcastTest)
    fan_out_broadcast = provide(FanOutBroadcast)
    finish_broadcast = provide(FinishBroadcast)

    @provide(scope=Scope.APP)
    def renderer(self, translator: Translator, telegram: TelegramSettings) -> NotificationRenderer:
        """Шаблоны читаются из каталогов процесса; кнопки ведут в Mini App окружения."""
        return GettextNotificationRenderer(translator, telegram.mini_app_url)
