"""Данные получателя в PostgreSQL — удалить вместе с аккаунтом (UserDeleted, ARCHITECTURE §7.10):
лента, доставки, каналы (chat_id Telegram), предпочтения и настройки. Доставки — первыми:
они ссылаются и на уведомления, и на каналы. Доставку, которую уже взяла задача отправки,
задача не найдёт — и ничего не отправит."""

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.infrastructure.models import (
    ChannelRow,
    DeliveryRow,
    NotificationRow,
    PreferenceRow,
    UserSettingsRow,
)
from app.platform.kernel.ids import UserId


class SqlRecipientData:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def forget(self, user_id: UserId) -> None:
        notifications = select(NotificationRow.id).where(NotificationRow.user_id == user_id)
        channels = select(ChannelRow.id).where(ChannelRow.user_id == user_id)
        await self._session.execute(
            delete(DeliveryRow).where(
                or_(
                    DeliveryRow.notification_id.in_(notifications),
                    DeliveryRow.channel_id.in_(channels),
                )
            )
        )
        for table in (NotificationRow, ChannelRow, PreferenceRow, UserSettingsRow):
            await self._session.execute(delete(table).where(table.user_id == user_id))
