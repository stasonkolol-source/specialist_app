"""ORM-модели reviews (ARCHITECTURE §7.3; миграции reviews_0001–0002).

`reviews.reviews` — отзывы по сделкам (7.2): клиент о исполнителе, проверка, публикация, ответ
исполнителя. `reviews.rating_aggregates` — рейтинг профилей, его пересчитывают опубликованные и
снятые отзывы; профиль без строки показывается «Новым специалистом». Отзывы «до платформы» в
рейтинг не входят (ADR-0016). FK на identity.users, deals.deals и specialists.profiles объявлены
только в миграциях: MetaData модуля не знает чужих таблиц (modules/README.md).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Integer, Numeric, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.reviews.domain.review import (
    MAX_BODY,
    MAX_REPLY,
    ReplyStatus,
    ReviewDirection,
    ReviewKind,
    ReviewStatus,
)
from app.platform.db.base import (
    ModelBase,
    TimestampsMixin,
    UuidPkMixin,
    VersionMixin,
    module_metadata,
)
from app.platform.db.types import str_enum

SCHEMA = "reviews"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class ReviewRow(UuidPkMixin, TimestampsMixin, VersionMixin, Base):
    __tablename__ = "reviews"

    kind: Mapped[ReviewKind] = mapped_column(
        str_enum(ReviewKind, "kind"), server_default=ReviewKind.DEAL.value
    )
    deal_id: Mapped[UUID | None]
    """deals.deals: FK в миграции; обязателен для `kind = 'deal'`."""
    author_id: Mapped[UUID]
    """identity.users: FK в миграции."""
    subject_user_id: Mapped[UUID]
    """identity.users: FK в миграции."""
    subject_profile_id: Mapped[UUID | None]
    """specialists.profiles: FK в миграции; чей рейтинг меняет отзыв."""
    category_id: Mapped[int | None]
    """Снимок категории сделки: её среднее — априорное в байесовском рейтинге."""
    direction: Mapped[ReviewDirection] = mapped_column(str_enum(ReviewDirection, "direction"))
    rating: Mapped[int] = mapped_column(SmallInteger)
    criteria: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    """{"quality": 5, "punctuality": 4, "communication": 5, "price": 4} — оценённые."""
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ReviewStatus] = mapped_column(
        str_enum(ReviewStatus, "status"), server_default=ReviewStatus.UNDER_REVIEW.value
    )
    reply_body: Mapped[str | None] = mapped_column(Text)
    reply_at: Mapped[datetime | None]
    reply_status: Mapped[ReplyStatus | None] = mapped_column(str_enum(ReplyStatus, "reply_status"))
    published_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        CheckConstraint(f"char_length(body) <= {MAX_BODY}", name="body_length"),
        CheckConstraint(f"char_length(reply_body) <= {MAX_REPLY}", name="reply_body_length"),
        CheckConstraint(
            "kind = 'pre_platform' OR deal_id IS NOT NULL", name="deal_review_has_deal"
        ),
        CheckConstraint(
            "(reply_body IS NULL) = (reply_status IS NULL)"
            " AND (reply_body IS NULL) = (reply_at IS NULL)",
            name="reply_complete",
        ),
        Index(
            "uq_reviews_deal_id_author_id",
            "deal_id",
            "author_id",
            unique=True,
            postgresql_where=text("deal_id IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index(
            "ix_reviews_subject_profile_id_published_at",
            "subject_profile_id",
            text("published_at DESC"),
            text("id DESC"),
            postgresql_where=text("status = 'published'"),
        ),
        Index("ix_reviews_author_id", "author_id"),
        Index("ix_reviews_subject_user_id", "subject_user_id"),
    )


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
    """Простое среднее."""
    rating_bayes: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    """Байесовское среднее: показ («4,9») и фильтр «рейтинг от»."""
    rating_lower_bound: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    """Нижняя граница доверительного интервала: ранжирование."""
    distribution: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{0,0,0,0,0}'")
    )
    """Сколько оценок в 1, 2, 3, 4 и 5 звёзд — гистограмма S11."""
    criteria_avg: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    """Средние по критериям: quality, punctuality, communication, price."""
    last_published_at: Mapped[datetime | None]
    """Когда опубликован последний отзыв (ADR-0016: показывается рядом с рейтингом)."""
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
