"""ORM-модели identity (ARCHITECTURE §7.3, миграции identity_0001–0005).

FK на таблицы других схем (`users.home_city_id` → geo.cities) объявлен только в миграции:
MetaData модуля не знает чужих таблиц, а ORM-ForeignKey на них не разрешился бы при
flush. `alembic check` такие FK не сравнивает (migrations/env.py).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.identity.domain.consent import ConsentDocument
from app.modules.identity.domain.deletion import DeletionSource, HashKind
from app.modules.identity.domain.restriction import RestrictionKind, RestrictionSource
from app.modules.identity.domain.session import RevokeReason
from app.modules.identity.domain.user import AuthProvider, UserIntent, UserStatus
from app.platform.db.base import (
    ModelBase,
    SoftDeleteMixin,
    TimestampsMixin,
    UuidPkMixin,
    VersionMixin,
    module_metadata,
    relation,
)
from app.platform.db.types import str_enum
from app.platform.kernel.ids import new_id
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Platform, Role

SCHEMA = "identity"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class UserRow(UuidPkMixin, TimestampsMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "users"

    status: Mapped[UserStatus] = mapped_column(
        str_enum(UserStatus, "status"), server_default=UserStatus.ACTIVE.value
    )
    display_name: Mapped[str] = mapped_column(String(64))
    avatar_media_id: Mapped[UUID | None]
    ui_locale: Mapped[Locale] = mapped_column(
        str_enum(Locale, "ui_locale"), server_default=Locale.RU.value
    )
    timezone: Mapped[str] = mapped_column(String(64), server_default="Europe/Belgrade")
    home_city_id: Mapped[int | None] = mapped_column(Integer)
    """geo.cities: FK fk_users_home_city_id_cities — в миграции identity_0002."""
    intent: Mapped[UserIntent | None] = mapped_column(str_enum(UserIntent, "intent"))
    phone_e164: Mapped[str | None] = mapped_column(String(16))
    phone_verified_at: Mapped[datetime | None]
    trust_penalty_at: Mapped[datetime | None]
    """Последнее нарушение (санкция или подтверждённая жалоба): отсчёт 14 дней, 2.5a."""
    identity_verified_at: Mapped[datetime | None]
    trust_level: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    privacy: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    last_seen_at: Mapped[datetime | None]
    identities: Mapped[list[AuthIdentityRow]] = relation(
        back_populates="user", cascade="all, delete-orphan", order_by="AuthIdentityRow.created_at"
    )

    __table_args__ = (
        Index(
            "uq_users_phone_e164",
            "phone_e164",
            unique=True,
            postgresql_where=text("phone_e164 IS NOT NULL AND deleted_at IS NULL"),
        ),
        CheckConstraint("trust_level BETWEEN 0 AND 3", name="trust_level_range"),
        # кандидаты ежедневного identity.trust_aging (миграция identity_0003)
        Index("ix_users_trust_aging", "created_at", postgresql_where=text("trust_level = 0")),
    )


class AuthIdentityRow(UuidPkMixin, Base):
    __tablename__ = "auth_identities"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[AuthProvider] = mapped_column(str_enum(AuthProvider, "provider"))
    subject: Mapped[str] = mapped_column(String(255))
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_login_at: Mapped[datetime | None]
    user: Mapped[UserRow] = relation(back_populates="identities")

    __table_args__ = (UniqueConstraint("provider", "subject"),)


class SessionRow(UuidPkMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    platform: Mapped[Platform] = mapped_column(str_enum(Platform, "platform"))
    bot_id: Mapped[int | None] = mapped_column(BigInteger)
    amr: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    refresh_token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), unique=True)
    previous_refresh_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32))
    rotated_at: Mapped[datetime | None]
    device: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    revoke_reason: Mapped[RevokeReason | None] = mapped_column(
        str_enum(RevokeReason, "revoke_reason")
    )

    __table_args__ = (
        Index("ix_sessions_user_id_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )


class RestrictionRow(UuidPkMixin, Base):
    __tablename__ = "restrictions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[RestrictionKind] = mapped_column(str_enum(RestrictionKind, "kind"))
    reason_code: Mapped[str] = mapped_column(String(64))
    source: Mapped[RestrictionSource] = mapped_column(str_enum(RestrictionSource, "source"))
    case_id: Mapped[UUID | None]
    """moderation.cases — без FK: moderation выше по DAG."""
    starts_at: Mapped[datetime] = mapped_column(server_default=func.now())
    ends_at: Mapped[datetime | None]
    lifted_at: Mapped[datetime | None]
    created_by: Mapped[UUID | None]

    __table_args__ = (
        Index(
            "ix_restrictions_user_id_in_force",
            "user_id",
            postgresql_where=text("lifted_at IS NULL"),
        ),
    )


class ConsentRow(UuidPkMixin, Base):
    """Журнал согласий (ст. 12–15 ZET, ст. 15 ZZPL): отзыв — withdrawn_at, строки не удаляются."""

    __tablename__ = "consents"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    document: Mapped[ConsentDocument] = mapped_column(str_enum(ConsentDocument, "document"))
    version: Mapped[str] = mapped_column(String(64))
    granted_at: Mapped[datetime] = mapped_column(server_default=func.now())
    withdrawn_at: Mapped[datetime | None]
    source: Mapped[Platform] = mapped_column(str_enum(Platform, "source"))
    ip: Mapped[str | None] = mapped_column(INET)

    __table_args__ = (
        Index(
            "uq_consents_user_id_document_version",
            "user_id",
            "document",
            "version",
            unique=True,
            postgresql_where=text("withdrawn_at IS NULL"),
        ),
    )


class UserRoleRow(Base):
    """Роли персонала. «Клиент» и «исполнитель» — возможности, а не роли."""

    __tablename__ = "user_roles"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[Role] = mapped_column(str_enum(Role, "role"), primary_key=True)
    granted_by: Mapped[UUID | None]
    granted_at: Mapped[datetime] = mapped_column(server_default=func.now())


class StatusHistoryRow(Base):
    __tablename__ = "status_history"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[UUID | None]
    reason: Mapped[str | None]
    at: Mapped[datetime]


class DeletionRequestRow(UuidPkMixin, Base):
    """Запрос на удаление аккаунта (§7.10): grace 7 дней, исполняет identity.process_deletions."""

    __tablename__ = "deletion_requests"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    requested_at: Mapped[datetime]
    execute_after: Mapped[datetime]
    """requested_at + 7 дней."""
    cancelled_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    source: Mapped[DeletionSource] = mapped_column(str_enum(DeletionSource, "source"))

    __table_args__ = (
        # у пользователя — не больше одного ждущего запроса
        Index(
            "uq_deletion_requests_user_id_active",
            "user_id",
            unique=True,
            postgresql_where=text("cancelled_at IS NULL AND completed_at IS NULL"),
        ),
        # ждущие запросы по сроку — для identity.process_deletions
        Index(
            "ix_deletion_requests_execute_after",
            "execute_after",
            postgresql_where=text("cancelled_at IS NULL AND completed_at IS NULL"),
        ),
    )


class DeletedIdentityHashRow(Base):
    """HMAC Telegram ID или телефона удалённого аккаунта: антифрод 12 месяцев (§7.10)."""

    __tablename__ = "deleted_identity_hashes"

    hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    kind: Mapped[HashKind] = mapped_column(str_enum(HashKind, "kind"))
    had_sanctions: Mapped[bool] = mapped_column(server_default=text("false"))
    deleted_at: Mapped[datetime]
    purge_after: Mapped[datetime]
    """deleted_at + 12 месяцев: дальше хэш удаляет platform.retention_sweep (2.12b)."""


class CompletedDealRow(Base):
    """Завершённая сделка стороны (6.1a): из числа таких — уровень доверия 2. Ключ — пара
    (пользователь, сделка): повтор задачи-подписчика факт не удваивает."""

    __tablename__ = "completed_deals"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    deal_id: Mapped[UUID] = mapped_column(primary_key=True)
    """deals.deals — модуль выше по DAG: без FK."""
    completed_at: Mapped[datetime]
