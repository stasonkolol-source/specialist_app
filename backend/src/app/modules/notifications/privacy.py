"""Выгрузка данных notifications (DEVELOPMENT_PLAN 2.12b): каналы, настройки, лента и
доставки уведомлений пользователя."""

from sqlalchemy import select

from app.modules.notifications.infrastructure.models import (
    ChannelRow,
    DeliveryRow,
    NotificationRow,
    PreferenceRow,
    UserSettingsRow,
)
from app.platform.privacy.registry import ExportTable, export_section

export_section(
    "notifications",
    ExportTable(ChannelRow, lambda user: ChannelRow.user_id == user),
    ExportTable(PreferenceRow, lambda user: PreferenceRow.user_id == user),
    ExportTable(UserSettingsRow, lambda user: UserSettingsRow.user_id == user),
    ExportTable(NotificationRow, lambda user: NotificationRow.user_id == user),
    ExportTable(
        DeliveryRow,
        lambda user: DeliveryRow.notification_id.in_(
            select(NotificationRow.id).where(NotificationRow.user_id == user)
        ),
    ),
)
