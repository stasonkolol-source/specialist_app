"""Чтение notifications для владельца: центр уведомлений (S42) и настройки (S43).

Текст уведомления собирается при показе на языке запроса: сменил язык — центр сразу на
новом языке, а в базе нет копий текста на каждом языке.
"""

from app.modules.notifications.application.dto import (
    NotificationFeed,
    NotificationView,
    SettingsView,
)
from app.modules.notifications.application.ports import NotificationQuery, NotificationRenderer
from app.platform.kernel.ids import UserId
from app.platform.kernel.localized import Locale
from app.platform.kernel.pagination import Page, PageRequest


class NotificationQueries:
    def __init__(self, query: NotificationQuery, renderer: NotificationRenderer) -> None:
        self._query, self._renderer = query, renderer

    async def feed(self, user_id: UserId, request: PageRequest, locale: Locale) -> NotificationFeed:
        records = await self._query.page(user_id, request)
        views = []
        for record in records.items:
            text = self._renderer.text(record.type, record.params, locale)
            views.append(
                NotificationView(
                    id=record.id,
                    type=record.type,
                    title=text.title,
                    body=text.body,
                    link=record.link,
                    created_at=record.created_at,
                    read=record.read_at is not None,
                )
            )
        return NotificationFeed(
            page=Page(items=tuple(views), next_cursor=records.next_cursor),
            unread=await self._query.unread(user_id),
        )

    async def settings(self, user_id: UserId) -> SettingsView:
        return SettingsView(
            settings=await self._query.settings(user_id),
            telegram=await self._query.telegram_channel(user_id),
        )
