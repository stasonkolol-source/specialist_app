"""ORM-модели notifications (ARCHITECTURE §7.3, миграции notifications_0001–0002, рассылки —
notifications_0008).

FK `user_id` → identity.users объявлены только в миграциях: MetaData модуля не знает
чужих таблиц (modules/README.md, migrations/env.py).
"""

from datetime import datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.notifications.domain.broadcast import Audience, BroadcastAction, BroadcastStatus
from app.modules.notifications.domain.catalog import Channel, EventGroup, NotificationType
from app.modules.notifications.domain.channel import ChannelKind, GrantedVia
from app.modules.notifications.domain.notification import DeliveryStatus
from app.modules.notifications.domain.settings import DIGEST_HOUR, QUIET_END, QUIET_START
from app.platform.db.base import ModelBase, TimestampsMixin, UuidPkMixin, module_metadata
from app.platform.db.types import str_enum

SCHEMA = "notifications"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class ChannelRow(UuidPkMixin, TimestampsMixin, Base):
    """Куда доставлять: личный чат с ботом (telegram), позже токены APNs/FCM и e-mail."""

    __tablename__ = "channels"

    user_id: Mapped[UUID]
    """identity.users: FK fk_channels_user_id_users — в миграции notifications_0001."""
    kind: Mapped[ChannelKind] = mapped_column(str_enum(ChannelKind, "kind"))
    address: Mapped[str] = mapped_column(String(255))
    """chat_id личного чата (= Telegram id), токен устройства или e-mail. Не логируется."""
    granted_via: Mapped[GrantedVia] = mapped_column(str_enum(GrantedVia, "granted_via"))
    granted_at: Mapped[datetime]
    disabled_at: Mapped[datetime | None]
    """Бот заблокирован (403) или токен отозван — шаг 2.3; новое разрешение снимает."""

    __table_args__ = (
        UniqueConstraint("kind", "address"),
        Index("ix_channels_user_id", "user_id"),
    )


class PreferenceRow(Base):
    """Выбор «группа × канал» — только то, что человек менял (умолчания — в домене)."""

    __tablename__ = "preferences"

    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    event_group: Mapped[EventGroup] = mapped_column(
        str_enum(EventGroup, "event_group"), primary_key=True
    )
    channel: Mapped[Channel] = mapped_column(str_enum(Channel, "channel"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class UserSettingsRow(Base):
    """Тихие часы и час дайджеста (S43); строки нет — умолчания."""

    __tablename__ = "user_settings"

    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    quiet_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    quiet_start: Mapped[time] = mapped_column(
        Time, server_default=text(f"'{QUIET_START.isoformat()}'")
    )
    """По часам Europe/Belgrade."""
    quiet_end: Mapped[time] = mapped_column(Time, server_default=text(f"'{QUIET_END.isoformat()}'"))
    digest_hour: Mapped[int] = mapped_column(SmallInteger, server_default=text(str(DIGEST_HOUR)))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("digest_hour BETWEEN 0 AND 23", name="digest_hour"),
        CheckConstraint("quiet_start <> quiet_end", name="quiet_window"),
    )


class NotificationRow(UuidPkMixin, Base):
    """Центр уведомлений (S42) и источник доставок."""

    __tablename__ = "notifications"

    user_id: Mapped[UUID]
    type: Mapped[NotificationType] = mapped_column(str_enum(NotificationType, "type"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    """Машинные параметры шаблона (`params`) и код deep link (`link`): текст собирается при
    показе на языке читателя."""
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True)
    priority: Mapped[int] = mapped_column(SmallInteger)
    in_app: Mapped[bool] = mapped_column(Boolean)
    """Виден в центре уведомлений (канал `in_app` включён для группы)."""
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint("priority BETWEEN 0 AND 4", name="priority"),
        # лента S42 по курсору: id — UUIDv7, растёт со временем
        Index("ix_notifications_user_id_id", "user_id", "id", postgresql_where=text("in_app")),
        Index(
            "ix_notifications_unread",
            "user_id",
            postgresql_where=text("in_app AND read_at IS NULL"),
        ),
        # счётчики и отмена рассылки — по префиксу ключа `broadcast:<id>:` (LIKE 'p%')
        Index(
            "ix_notifications_broadcast",
            "dedupe_key",
            postgresql_ops={"dedupe_key": "text_pattern_ops"},
            postgresql_where=text("type = 'broadcast'"),
        ),
    )


class DeliveryRow(UuidPkMixin, TimestampsMixin, Base):
    """Отправка уведомления в один канал не раньше `not_before`."""

    __tablename__ = "deliveries"

    notification_id: Mapped[UUID] = mapped_column(ForeignKey("notifications.id"))
    channel_id: Mapped[UUID] = mapped_column(ForeignKey("channels.id"))
    status: Mapped[DeliveryStatus] = mapped_column(str_enum(DeliveryStatus, "status"))
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    provider_message_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(String(255))
    not_before: Mapped[datetime]
    """Тихие часы; позже — дебаунс, дайджест и пауза после 429."""
    sent_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint("notification_id", "channel_id"),
        Index("ix_deliveries_not_before", "not_before", postgresql_where=text("status = 'queued'")),
    )


class BroadcastRow(UuidPkMixin, TimestampsMixin, Base):
    """Рассылка из админки (2.7b): текст, кнопка, аудитория и ход разбора получателей."""

    __tablename__ = "broadcasts"

    status: Mapped[BroadcastStatus] = mapped_column(str_enum(BroadcastStatus, "status"))
    event_group: Mapped[EventGroup] = mapped_column(str_enum(EventGroup, "event_group"))
    """Группа согласия S43: только opt-in (`marketing`, `goods_launch`)."""
    audience: Mapped[Audience] = mapped_column(str_enum(Audience, "audience"))
    city_id: Mapped[int | None] = mapped_column(Integer)
    """geo.cities; FK не нужен: город только сужает выборку."""
    text: Mapped[dict[str, str]] = mapped_column(JSONB)
    """Тексты по кодам локалей (LocalizedText)."""
    link: Mapped[str | None] = mapped_column(String(64))
    """Код deep link кнопки «Открыть» (§11.4)."""
    action: Mapped[BroadcastAction | None] = mapped_column(str_enum(BroadcastAction, "action"))
    created_by: Mapped[UUID]
    """Сотрудник (identity.users): FK fk_broadcasts_created_by_users — в миграции."""
    starts_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    cursor: Mapped[UUID | None]
    """Последний разобранный получатель: следующая пачка — после него."""

    __table_args__ = (
        CheckConstraint("event_group IN ('marketing', 'goods_launch')", name="opt_in_group"),
        CheckConstraint("link IS NULL OR action IS NULL", name="one_button"),
        Index("ix_broadcasts_created_at", "created_at"),
    )
