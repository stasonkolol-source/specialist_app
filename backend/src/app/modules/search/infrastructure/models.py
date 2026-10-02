"""ORM-модели search (ARCHITECTURE §7.3, миграции search_0001–0002): read-model специалистов
и журнал запросов без результатов.

Таблицы — проекция: источник правды — модули ниже по DAG, строки пересобирает проектор.
FK на чужие схемы нет — у read-model их и не должно быть: строка удаляется событием.
Индексы — набор лаборатории (research/07 §3.4, lab/sql/15): частичные `WHERE is_listed`.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, REAL, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db.base import ModelBase, module_metadata
from app.platform.db.types import GeoPointType
from app.platform.kernel.geo import GeoPoint

SCHEMA = "search"
metadata = module_metadata(SCHEMA)
LISTED = text("is_listed")


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class SpecialistIndexRow(Base):
    __tablename__ = "specialist_index"

    profile_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(16))
    is_listed: Mapped[bool] = mapped_column(Boolean)
    city_id: Mapped[int] = mapped_column(Integer)
    district_id: Mapped[int | None] = mapped_column(Integer)
    district_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default=text("'{}'"))
    base_point: Mapped[GeoPoint | None] = mapped_column(GeoPointType)
    """Точная база — только фильтр «выезжает ко мне», наружу не отдаётся."""
    base_point_public: Mapped[GeoPoint | None] = mapped_column(GeoPointType)
    travel_radius_m: Mapped[int | None] = mapped_column(Integer)
    category_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    """Категории профиля и все их предки."""
    tag_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default=text("'{}'"))
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(8)))
    work_modes: Mapped[list[str]] = mapped_column(ARRAY(String(16)))
    price_from: Mapped[int | None] = mapped_column(BigInteger)
    """Пара."""
    rating_bayes: Mapped[float | None] = mapped_column(Numeric(4, 3))
    rating_lower_bound: Mapped[float | None] = mapped_column(Numeric(4, 3))
    rating_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    badges: Mapped[list[str]] = mapped_column(ARRAY(String(32)), server_default=text("'{}'"))
    available_until: Mapped[datetime | None]
    promoted_until: Mapped[datetime | None]
    activity_score: Mapped[float] = mapped_column(REAL, server_default=text("0"))
    score: Mapped[float] = mapped_column(REAL, server_default=text("0"))
    name_norm: Mapped[str | None] = mapped_column(Text)
    search_vector: Mapped[Any] = mapped_column(TSVECTOR)
    card: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_updated_at: Mapped[datetime]
    """Когда менялся профиль-источник: сверка и отладка рассинхрона."""
    indexed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_specialist_index_user_id", "user_id"),
        Index(
            "ix_specialist_index_category_ids",
            "category_ids",
            postgresql_using="gin",
            postgresql_where=LISTED,
        ),
        Index(
            "ix_specialist_index_search_vector",
            "search_vector",
            postgresql_using="gin",
            postgresql_where=LISTED,
        ),
        Index(
            "ix_specialist_index_base_point",
            "base_point",
            postgresql_using="gist",
            postgresql_where=text("is_listed AND base_point IS NOT NULL"),
        ),
        Index(
            "ix_specialist_index_base_point_public",
            "base_point_public",
            postgresql_using="gist",
            postgresql_where=text("is_listed AND base_point_public IS NOT NULL"),
        ),
        Index(
            "ix_specialist_index_city_id_score",
            "city_id",
            text("score DESC"),
            text("profile_id DESC"),
            postgresql_where=LISTED,
        ),
        Index(
            "ix_specialist_index_district_ids",
            "district_ids",
            postgresql_using="gin",
            postgresql_where=LISTED,
        ),
        Index(
            "ix_specialist_index_name_norm",
            "name_norm",
            postgresql_using="gist",
            postgresql_ops={"name_norm": "gist_trgm_ops"},
            postgresql_where=LISTED,
        ),
    )


class SpecialistCategoryPriceRow(Base):
    """Цена «от» профиля в категории (и её предках): фильтр «до N» в выбранной категории."""

    __tablename__ = "specialist_category_prices"

    category_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[UUID] = mapped_column(primary_key=True)
    price_from: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (Index("ix_specialist_category_prices_profile_id", "profile_id"),)


class PendingProfileRow(Base):
    """Очередь пересборки: профиль, который событие изменило, ждёт задачи search.flush_index."""

    __tablename__ = "pending_profiles"

    profile_id: Mapped[UUID] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime | None]
    """Самое раннее событие, которое ждёт пересборки; None — плановая пересборка."""
    marked_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_pending_profiles_marked_at", "marked_at"),)


class QueryLogRow(Base):
    """Запрос выдачи без результатов (§9.2): чего нет в словаре категорий. Без пользователя:
    для словаря важен текст, а не кто искал. Срок хранения — матрица 2.12b."""

    __tablename__ = "query_log"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))
    q: Mapped[str] = mapped_column(String(100))
    q_norm: Mapped[str] = mapped_column(
        # ::text — как PostgreSQL хранит выражение; иначе alembic check видит расхождение
        Text,
        Computed("platform.search_norm(q::text)", persisted=True),
    )
    locale: Mapped[str] = mapped_column(String(8))
    city_id: Mapped[int] = mapped_column(Integer)
    category_id: Mapped[int | None] = mapped_column(Integer)
    filters: Mapped[list[str]] = mapped_column(ARRAY(String(32)), server_default=text("'{}'"))
    did_you_mean: Mapped[str | None] = mapped_column(String(120))
    """Подсказка, которая тоже ничего не нашла."""
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_query_log_created_at", "created_at"),
        Index("ix_query_log_q_norm", "q_norm"),
    )
