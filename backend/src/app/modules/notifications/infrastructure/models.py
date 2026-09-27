"""ORM-модели notifications (ARCHITECTURE §7.3, миграция notifications_0001).

FK `channels.user_id` → identity.users объявлен только в миграции: MetaData модуля не
знает чужих таблиц (modules/README.md, migrations/env.py). Предпочтения, центр
уведомлений и доставки — шаг 2.3a.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.notifications.domain.channel import ChannelKind, GrantedVia
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
