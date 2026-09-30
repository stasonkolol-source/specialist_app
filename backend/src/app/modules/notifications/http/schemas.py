"""Схемы HTTP notifications (ADR-0020 §10: <Имя>In / <Имя>Out)."""

from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.notifications.application.dto import (
    ChannelView,
    NotificationFeed,
    NotificationView,
    SettingsView,
)
from app.modules.notifications.domain.catalog import (
    MANDATORY_GROUPS,
    Channel,
    EventGroup,
    NotificationType,
)
from app.modules.notifications.domain.channel import GrantedVia
from app.modules.notifications.domain.settings import (
    DIGEST_HOUR,
    QUIET_END,
    QUIET_START,
    TIMEZONE,
)
from app.platform.http.pagination import PageOut

MAX_READ_IDS = 100


class TelegramChannelOut(BaseModel):
    """Канал «бот пишет в личный чат»: Mini App решает, просить ли разрешение (S21, S02c)."""

    writable: bool
    """Бот может писать пользователю; false — бот заблокирован (шаг 2.3)."""
    granted_via: GrantedVia
    """Как получено разрешение: `bot_start` — /start в боте, `mini_app` — requestWriteAccess."""
    granted_at: datetime

    @classmethod
    def of(cls, view: ChannelView) -> TelegramChannelOut:
        return cls(writable=view.writable, granted_via=view.granted_via, granted_at=view.granted_at)


class NotificationOut(BaseModel):
    """Строка центра уведомлений (S42) на языке Accept-Language."""

    id: UUID
    type: NotificationType
    title: str
    body: str
    link: str | None
    """Код deep link (ARCHITECTURE §11.4): куда ведёт нажатие; null — никуда."""
    created_at: datetime
    read: bool

    @classmethod
    def of(cls, view: NotificationView) -> NotificationOut:
        return cls(
            id=view.id,
            type=view.type,
            title=view.title,
            body=view.body,
            link=view.link,
            created_at=view.created_at,
            read=view.read,
        )


class NotificationPageOut(PageOut[NotificationOut]):
    unread_count: int
    """Непрочитанных в центре — для бейджа."""

    @classmethod
    def of_feed(cls, feed: NotificationFeed) -> NotificationPageOut:
        return cls(
            items=[NotificationOut.of(view) for view in feed.page.items],
            next_cursor=feed.page.next_cursor,
            unread_count=feed.unread,
        )


class NotificationsReadIn(BaseModel):
    """Что отметить прочитанным: `ids` (до 100) или `all: true`."""

    ids: list[UUID] | None = Field(default=None, max_length=MAX_READ_IDS)
    all: bool = False

    @model_validator(mode="after")
    def _one_of(self) -> NotificationsReadIn:
        if (self.ids is None) == (not self.all):
            raise ValueError("either ids or all=true")
        return self


class UnreadOut(BaseModel):
    unread_count: int


class QuietHoursOut(BaseModel):
    enabled: bool
    start: time
    """По часам `time_zone`."""
    end: time
    time_zone: str = TIMEZONE.key
    """Часовой пояс тихих часов: в MVP — Сербия."""


class QuietHoursIn(BaseModel):
    enabled: bool
    start: time = QUIET_START
    end: time = QUIET_END
    """По часам Europe/Belgrade; начало и конец не совпадают."""


class GroupSettingOut(BaseModel):
    group: EventGroup
    telegram: bool
    """Бот пишет в личный чат."""
    in_app: bool
    """Видно в центре уведомлений (S42)."""
    mandatory: bool
    """Служебная группа (решения модерации, санкции): не выключается."""


class GroupSettingIn(BaseModel):
    group: EventGroup
    telegram: bool
    in_app: bool


class NotificationSettingsOut(BaseModel):
    groups: list[GroupSettingOut]
    quiet_hours: QuietHoursOut
    digest_hour: int
    """Час дайджеста подходящих заявок по Белграду (0–23)."""
    telegram: TelegramChannelOut | None
    """Бот может писать; null — разрешения ещё нет: Mini App предложит `requestWriteAccess`."""

    @classmethod
    def of(cls, view: SettingsView) -> NotificationSettingsOut:
        settings = view.settings
        allows = settings.preferences.allows
        quiet = settings.quiet_hours
        return cls(
            groups=[
                GroupSettingOut(
                    group=group,
                    telegram=allows(group, Channel.TELEGRAM),
                    in_app=allows(group, Channel.IN_APP),
                    mandatory=group in MANDATORY_GROUPS,
                )
                for group in EventGroup
            ],
            quiet_hours=QuietHoursOut(enabled=quiet.enabled, start=quiet.start, end=quiet.end),
            digest_hour=settings.digest_hour,
            telegram=TelegramChannelOut.of(view.telegram) if view.telegram else None,
        )


class NotificationSettingsIn(BaseModel):
    """Настройки целиком: группы, которых нет в списке, возвращаются к умолчаниям."""

    groups: list[GroupSettingIn] = Field(max_length=len(EventGroup))
    quiet_hours: QuietHoursIn
    digest_hour: int = Field(default=DIGEST_HOUR, ge=0, le=23)

    @model_validator(mode="after")
    def _unique_groups(self) -> NotificationSettingsIn:
        if len({g.group for g in self.groups}) != len(self.groups):
            raise ValueError("groups must be unique")
        return self
