"""ORM-модели media (ARCHITECTURE §7.3 «media: assets», миграция media_0001).

FK `assets.owner_id` → identity.users объявлен только в миграции: MetaData модуля не знает
чужих таблиц (modules/README.md). Поля обработки (варианты, размеры, sha256, placeholder,
модерация) заполняет шаг 2.2 — схема сразу полная, по DDL архитектуры; `phash` — шаг 7.6.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Index, Integer, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import BIT, JSONB, BitString
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.media.domain.asset import FailureReason, MediaStatus, ModerationStatus
from app.modules.media.domain.policy import MediaKind, MediaPurpose
from app.platform.db.base import ModelBase, UuidPkMixin, module_metadata
from app.platform.db.types import str_enum

SCHEMA = "media"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class AssetRow(UuidPkMixin, Base):
    """Медиафайл со своим жизненным циклом; к объектам привязывается связующими таблицами."""

    __tablename__ = "assets"

    owner_id: Mapped[UUID]
    """identity.users: FK fk_assets_owner_id_users — в миграции media_0001."""
    kind: Mapped[MediaKind] = mapped_column(str_enum(MediaKind, "kind"))
    purpose: Mapped[MediaPurpose] = mapped_column(str_enum(MediaPurpose, "purpose"))
    status: Mapped[MediaStatus] = mapped_column(
        str_enum(MediaStatus, "status"), server_default=MediaStatus.PENDING_UPLOAD.value
    )
    bucket: Mapped[str] = mapped_column(String(32))
    object_key: Mapped[str] = mapped_column(String(255))
    """`{purpose}/{yyyy}/{mm}/{id}/original`."""
    upload_id: Mapped[str | None] = mapped_column(Text)
    """Id multipart-загрузки в хранилище (видео больше 50 MB); у R2 длиннее 255 символов."""
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    etag: Mapped[str | None] = mapped_column(Text)
    """ETag оригинала, сверенного HEAD-ом при complete: обработка (2.2) читает именно его."""
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    phash: Mapped[BitString | None] = mapped_column(BIT(64))
    """pHash фото портфолио или постера ролика (media_0006): дубликаты — `bit_count(a # b)`."""
    variants: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    placeholder: Mapped[str | None] = mapped_column(Text)
    moderation_status: Mapped[ModerationStatus] = mapped_column(
        str_enum(ModerationStatus, "moderation_status"),
        server_default=ModerationStatus.PENDING.value,
    )
    moderation_labels: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    failure_reason: Mapped[FailureReason | None] = mapped_column(
        str_enum(FailureReason, "failure_reason")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    uploaded_at: Mapped[datetime | None]
    processed_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    """Сколько раз начиналась обработка (MAX_ATTEMPTS)."""
    deleted_at: Mapped[datetime | None]
    hidden_at: Mapped[datetime | None]
    """Варианты удалённого файла перенесены в private (media.hide_variants)."""
    held_until: Mapped[datetime | None]
    """Legal hold: очистка ждёт до этого времени (открытый кейс или спор, 2.5a)."""
    purged_at: Mapped[datetime | None]
    """Объекты удалённого файла стёрты (media.purge_deleted); запись остаётся."""

    __table_args__ = (
        Index("ix_assets_owner_id_created_at", "owner_id", text("created_at DESC")),
        Index(
            "ix_assets_status_created_at",
            "status",
            "created_at",
            postgresql_where=text("status IN ('pending_upload', 'uploaded', 'processing')"),
        ),
        Index(
            "ix_assets_deleted_at",
            "deleted_at",
            postgresql_where=text("status = 'deleted' AND purged_at IS NULL"),
        ),
    )
