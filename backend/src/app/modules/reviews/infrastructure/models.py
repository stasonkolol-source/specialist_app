"""ORM-модели reviews (ARCHITECTURE §7.3 `reviews.rating_aggregates`, миграция reviews_0001).

Агрегаты рейтинга профилей: их пересчитывают отзывы по сделкам (7.2), а пока таблица пуста —
профиль без строки показывается «Новым специалистом». Отзывы «до платформы» в рейтинг не входят
(ADR-0016). FK на specialists.profiles объявлен только в миграции: MetaData модуля не знает
чужих таблиц (modules/README.md).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Integer, Numeric, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db.base import ModelBase, module_metadata

SCHEMA = "reviews"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class RatingAggregateRow(Base):
    __tablename__ = "rating_aggregates"
    __table_args__ = (
        CheckConstraint("rating_count >= 0", name="rating_count_non_negative"),
        CheckConstraint("cardinality(distribution) = 5", name="distribution_five_stars"),
    )

    subject_profile_id: Mapped[UUID] = mapped_column(primary_key=True)
    """specialists.profiles: FK fk_rating_aggregates_subject_profile_id_profiles — в миграции."""
    rating_count: Mapped[int] = mapped_column(Integer)
    rating_avg: Mapped[Decimal] = mapped_column(Numeric(3, 2))
    """Среднее для показа: «4,9»."""
    rating_bayes: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    """Байесовское среднее: фильтр «рейтинг от»."""
    rating_lower_bound: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    """Нижняя граница доверительного интервала: ранжирование."""
    distribution: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{0,0,0,0,0}'")
    )
    """Сколько оценок в 1, 2, 3, 4 и 5 звёзд — гистограмма S11."""
    criteria_avg: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    """Средние по критериям: quality, punctuality, communication, price."""
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
