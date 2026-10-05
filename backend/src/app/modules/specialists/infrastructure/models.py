"""ORM-модели specialists (ARCHITECTURE §7.3, миграции specialists_0001–0002).

FK на identity.users, geo.cities, geo.districts, catalog.categories и media.assets объявлены
только в миграциях: MetaData модуля не знает чужих таблиц (modules/README.md). Рабочие часы —
v1; колонки-задел v1 из DDL — без логики.
"""

from datetime import date, datetime
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
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.specialists.domain.portfolio import MAX_CAPTION, WorkKind, WorkStatus
from app.modules.specialists.domain.profile import (
    MAX_ABOUT,
    MAX_HEADLINE,
    MAX_NAME,
    ProfileKind,
    ProfileStatus,
)
from app.platform.db.base import (
    ModelBase,
    SoftDeleteMixin,
    TimestampsMixin,
    UuidPkMixin,
    VersionMixin,
    module_metadata,
)
from app.platform.db.types import GeoPointType, str_enum
from app.platform.kernel.geo import GeoPoint

SCHEMA = "specialists"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class ProfileRow(UuidPkMixin, TimestampsMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "profiles"

    user_id: Mapped[UUID]
    """identity.users: FK fk_profiles_user_id_users — в миграции specialists_0001."""
    kind: Mapped[ProfileKind] = mapped_column(str_enum(ProfileKind, "kind"))
    status: Mapped[ProfileStatus] = mapped_column(
        str_enum(ProfileStatus, "status"), server_default=ProfileStatus.DRAFT.value
    )
    display_name: Mapped[str] = mapped_column(String(MAX_NAME))
    headline: Mapped[str | None] = mapped_column(Text)
    about: Mapped[str | None] = mapped_column(Text)
    content_lang: Mapped[str | None] = mapped_column(String(8))
    experience_since: Mapped[int | None] = mapped_column(SmallInteger)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(8)), server_default=text("'{}'"))
    city_id: Mapped[int] = mapped_column(Integer)
    """geo.cities: FK в миграции."""
    district_id: Mapped[int | None] = mapped_column(Integer)
    """geo.districts: основной район (первый из районов выезда)."""
    base_point: Mapped[GeoPoint | None] = mapped_column(GeoPointType)
    """Точная база — только для фильтра «выезжает ко мне», наружу не отдаётся."""
    base_point_public: Mapped[GeoPoint | None] = mapped_column(GeoPointType)
    travel_radius_km: Mapped[int | None] = mapped_column(SmallInteger)
    work_modes: Mapped[list[str]] = mapped_column(ARRAY(String(16)), server_default=text("'{}'"))
    available_until: Mapped[datetime | None]
    stale_reminded_at: Mapped[datetime | None]
    """Последнее «профиль давно не обновлялся» (specialists_0003, 5.7): не чаще раза в 2 недели."""
    vacation_until: Mapped[date | None]
    trader_status: Mapped[str | None] = mapped_column(String(16))
    """v1 (ADR-0018): декларация trader / non_trader."""
    registry_id: Mapped[str | None] = mapped_column(Text)
    business_verified_at: Mapped[datetime | None]
    contacts: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    listed_in_catalog: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    is_founding: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    """Founding (§15.2): `cli founding-mark`; бейджа в MVP нет."""
    pro_waitlist_at: Mapped[datetime | None]
    """Лист ожидания Pro (Q24): кнопка в рассылке бота (2.7b)."""
    rejection_reason: Mapped[str | None] = mapped_column(String(64))
    reviewed_kind: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    slug: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None]
    published_at: Mapped[datetime | None]
    avatar_media_id: Mapped[UUID | None]
    revision: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    """Редакция содержимого (specialists_0004, domain Profile.revision): версия для модерации."""
    """Фото профиля — media.assets (назначение avatar): FK в миграции specialists_0002."""

    __table_args__ = (
        CheckConstraint(f"char_length(headline) <= {MAX_HEADLINE}", name="headline_length"),
        CheckConstraint(f"char_length(about) <= {MAX_ABOUT}", name="about_length"),
        CheckConstraint("travel_radius_km IN (3, 5, 10)", name="travel_radius"),
        CheckConstraint("trader_status IN ('trader', 'non_trader')", name="trader_status"),
        Index(
            "uq_profiles_user_id_alive",
            "user_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_profiles_status_city_id",
            "status",
            "city_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_profiles_slug",
            "slug",
            unique=True,
            postgresql_where=text("slug IS NOT NULL AND deleted_at IS NULL"),
        ),
    )


class ProfileCategoryRow(Base):
    __tablename__ = "profile_categories"

    profile_id: Mapped[UUID] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    category_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    """catalog.categories: FK в миграции."""
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


class ServiceAreaRow(Base):
    """Районы, куда исполнитель выезжает (если не весь город)."""

    __tablename__ = "service_areas"

    profile_id: Mapped[UUID] = mapped_column(ForeignKey("profiles.id"), primary_key=True)
    district_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    """geo.districts: FK в миграции."""
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


class PortfolioItemRow(UuidPkMixin, SoftDeleteMixin, Base):
    """Работа портфолио: фото или ролик с подписью (в MVP — один файл, альбомы — потом)."""

    __tablename__ = "portfolio_items"

    profile_id: Mapped[UUID] = mapped_column(ForeignKey("profiles.id"))
    category_id: Mapped[int | None] = mapped_column(Integer)
    """catalog.categories: FK в миграции."""
    title: Mapped[str | None] = mapped_column(Text)
    """Подпись работы на S37."""
    description: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    status: Mapped[WorkStatus] = mapped_column(
        str_enum(WorkStatus, "status"), server_default=WorkStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    revision: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    """Редакция подписи (specialists_0004, domain PortfolioItem.revision): версия для модерации."""

    __table_args__ = (
        CheckConstraint(f"char_length(title) <= {MAX_CAPTION}", name="title_length"),
        Index(
            "ix_portfolio_items_profile_id",
            "profile_id",
            "position",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class PortfolioMediaRow(Base):
    """Файлы работы: в MVP — один; `kind` — для лимитов 60 фото и 6 роликов."""

    __tablename__ = "portfolio_media"

    item_id: Mapped[UUID] = mapped_column(ForeignKey("portfolio_items.id"), primary_key=True)
    media_id: Mapped[UUID] = mapped_column(primary_key=True)
    """media.assets: FK в миграции."""
    kind: Mapped[WorkKind] = mapped_column(str_enum(WorkKind, "kind"))
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
