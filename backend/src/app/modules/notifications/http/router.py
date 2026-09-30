"""HTTP notifications (ARCHITECTURE §8.5, §11): каналы, центр уведомлений, настройки.

Экраны центра (S42) и настроек (S43) — шаг 4.9; API — с 2.3a.
"""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter

from app.modules.notifications.application.queries import NotificationQueries
from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
    GrantTelegramWriteAccessCommand,
)
from app.modules.notifications.application.use_cases.mark_notifications_read import (
    MarkNotificationsRead,
    MarkNotificationsReadCommand,
)
from app.modules.notifications.application.use_cases.update_notification_settings import (
    UpdateNotificationSettings,
    UpdateNotificationSettingsCommand,
)
from app.modules.notifications.domain.catalog import Channel
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.domain.notification import NotificationId
from app.modules.notifications.domain.settings import QuietHours
from app.modules.notifications.http.schemas import (
    NotificationPageOut,
    NotificationSettingsIn,
    NotificationSettingsOut,
    NotificationsReadIn,
    TelegramChannelOut,
    UnreadOut,
)
from app.platform.http.pagination import PageParams
from app.platform.http.security import AUTHENTICATED
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Principal

router = APIRouter(tags=["notifications"])


@router.post("/me/telegram/write-access", dependencies=AUTHENTICATED)
@inject
async def grant_telegram_write_access(
    principal: FromDishka[Principal], grant: FromDishka[GrantTelegramWriteAccess]
) -> TelegramChannelOut:
    """Пользователь разрешил боту писать: Mini App вызывает после успешного `requestWriteAccess`.

    Повтор идемпотентен: доступный канал не меняется. Нет Telegram-аккаунта — 409
    `telegram_not_linked`.
    """
    channel = await grant(
        GrantTelegramWriteAccessCommand(user_id=principal.user_id, via=GrantedVia.MINI_APP)
    )
    return TelegramChannelOut.of(channel)


@router.get("/me/notifications", dependencies=AUTHENTICATED)
@inject
async def list_notifications(
    principal: FromDishka[Principal],
    queries: FromDishka[NotificationQueries],
    locale: FromDishka[Locale],
    page: PageParams,
) -> NotificationPageOut:
    """Центр уведомлений: новые сверху, по курсору; тексты — на языке Accept-Language."""
    return NotificationPageOut.of_feed(await queries.feed(principal.user_id, page, locale))


@router.post("/me/notifications/read", dependencies=AUTHENTICATED)
@inject
async def mark_notifications_read(
    body: NotificationsReadIn,
    principal: FromDishka[Principal],
    mark: FromDishka[MarkNotificationsRead],
) -> UnreadOut:
    """Отметить прочитанными `ids` или все (`all: true`); чужие id не находятся. Повтор
    идемпотентен. Ответ — сколько непрочитанных осталось."""
    ids = [NotificationId(i) for i in body.ids] if body.ids is not None else None
    unread = await mark(MarkNotificationsReadCommand(user_id=principal.user_id, ids=ids))
    return UnreadOut(unread_count=unread)


@router.get("/me/notification-settings", dependencies=AUTHENTICATED)
@inject
async def get_notification_settings(
    principal: FromDishka[Principal], queries: FromDishka[NotificationQueries]
) -> NotificationSettingsOut:
    """Группы × каналы, тихие часы, час дайджеста и может ли бот писать (S43)."""
    return NotificationSettingsOut.of(await queries.settings(principal.user_id))


@router.put("/me/notification-settings", dependencies=AUTHENTICATED)
@inject
async def update_notification_settings(
    body: NotificationSettingsIn,
    principal: FromDishka[Principal],
    update: FromDishka[UpdateNotificationSettings],
) -> NotificationSettingsOut:
    """Заменить настройки целиком; группы, которых нет в списке, — по умолчанию. Служебную
    группу выключить нельзя — 422 `notification_group_mandatory`."""
    choices = {}
    for g in body.groups:
        choices[(g.group, Channel.TELEGRAM)] = g.telegram
        choices[(g.group, Channel.IN_APP)] = g.in_app
    view = await update(
        UpdateNotificationSettingsCommand(
            user_id=principal.user_id,
            choices=choices,
            quiet_hours=QuietHours(
                enabled=body.quiet_hours.enabled,
                start=body.quiet_hours.start,
                end=body.quiet_hours.end,
            ),
            digest_hour=body.digest_hour,
        )
    )
    return NotificationSettingsOut.of(view)
