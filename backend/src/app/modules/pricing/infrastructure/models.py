"""ORM-модели pricing (ARCHITECTURE §7.3 `pricing.services`, миграция pricing_0001).

FK на specialists.profiles и catalog.categories объявлены только в миграции: MetaData модуля
не знает чужих таблиц (modules/README.md).
"""

from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.pricing.domain.service import MAX_TITLE, MAX_UNIT, PriceType
from app.platform.db.base import (
    ModelBase,
    SoftDeleteMixin,
    TimestampsMixin,
    UuidPkMixin,
    module_metadata,
)
from app.platform.db.types import rsd_only, str_enum

SCHEMA = "pricing"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class ServiceRow(UuidPkMixin, TimestampsMixin, SoftDeleteMixin, Base):
    __tablename__ = "services"

    profile_id: Mapped[UUID]
    """specialists.profiles: FK fk_services_profile_id_profiles — в миграции pricing_0001."""
    category_id: Mapped[int | None] = mapped_column(Integer)
    """catalog.categories: группа в S35."""
    title: Mapped[str] = mapped_column(String(MAX_TITLE))
    description: Mapped[str | None] = mapped_column(Text)
    price_type: Mapped[PriceType] = mapped_column(str_enum(PriceType, "price_type"))
    price_min: Mapped[int | None] = mapped_column(BigInteger)
    """Пара: 1 RSD = 100 пара."""
    price_max: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), server_default="RSD")
    unit: Mapped[str | None] = mapped_column(String(MAX_UNIT))
    duration_min: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        rsd_only("currency"),
        CheckConstraint("price_type = 'negotiable' OR price_min IS NOT NULL", name="price_set"),
        CheckConstraint("price_max IS NULL OR price_max >= price_min", name="price_range"),
        Index(
            "ix_services_profile_id_position",
            "profile_id",
            "position",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
