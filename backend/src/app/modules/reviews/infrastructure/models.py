"""ORM-модели reviews (ARCHITECTURE §7.3; миграции reviews_0001–0004).

`reviews.reviews` — отзывы по сделкам (7.2): клиент о исполнителе, проверка, публикация, ответ
исполнителя. `reviews.rating_aggregates` — рейтинг профилей, его пересчитывают опубликованные и
снятые отзывы; профиль без строки показывается «Новым специалистом». Отзывы «до платформы» в
рейтинг не входят (ADR-0016), их пишут по ссылкам `reviews.review_invites` (7.6а). FK на
identity.users, deals.deals и specialists.profiles объявлены только в миграциях: MetaData модуля
не знает чужих таблиц (modules/README.md).
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.reviews.domain.invite import MAX_CLIENT_NAME
from app.modules.reviews.domain.review import (
    MAX_BODY,
    MAX_REPLY,
    MAX_WORK_TITLE,
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
    work_title: Mapped[str | None] = mapped_column(Text)
    """«Что делал мастер» — у отзыва до платформы (7.6а) вместо названия сделки."""

    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        CheckConstraint(f"char_length(body) <= {MAX_BODY}", name="body_length"),
        CheckConstraint(f"char_length(work_title) <= {MAX_WORK_TITLE}", name="work_title_length"),
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
            "uq_reviews_subject_profile_id_author_id",
            "subject_profile_id",
            "author_id",
            unique=True,
            postgresql_where=text("kind = 'pre_platform' AND deleted_at IS NULL"),
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


class ReviewInviteRow(Base):
    """Ссылка-приглашение прошлому клиенту на «отзыв до платформы» (7.6а): не больше пяти
    занятых мест на профиль — проверка в приложении под advisory lock профиля. Отозванная
    ссылка удаляется: для чужого она то же, что несуществующая."""

    __tablename__ = "review_invites"

    token: Mapped[UUID] = mapped_column(primary_key=True)
    """Секрет ссылки `ri_<base62>` — случайный UUIDv4 (в §7.3 — text; uuid — тот же кодек
    ссылок, что у сущностей)."""
    profile_id: Mapped[UUID]
    """specialists.profiles: FK в миграции."""
    client_name: Mapped[str | None] = mapped_column(Text)
    """Кому отправлена ссылка — заметка специалиста для списка S55, по желанию."""
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    used_by: Mapped[UUID | None]
    """identity.users: FK в миграции; кто оставил отзыв."""
    used_at: Mapped[datetime | None]
    review_id: Mapped[UUID | None] = mapped_column(ForeignKey(ReviewRow.id))
    """Отзыв, оставленный по ссылке."""

    __table_args__ = (
        CheckConstraint(
            f"char_length(client_name) <= {MAX_CLIENT_NAME}", name="client_name_length"
        ),
        CheckConstraint(
            "(used_by IS NULL) = (used_at IS NULL) AND (used_by IS NULL) = (review_id IS NULL)",
            name="use_complete",
        ),
        Index("ix_review_invites_profile_id", "profile_id", text("created_at DESC")),
        Index("ix_review_invites_used_by", "used_by"),
    )


class ReviewRequestRow(Base):
    """Просьба оставить отзыв по завершённой сделке (7.2): когда напомнили. Отзыв по сделке есть
    или окно закрылось — напоминаний больше нет (проверка — при отправке)."""

    __tablename__ = "review_requests"

    deal_id: Mapped[UUID] = mapped_column(primary_key=True)
    """deals.deals: FK в миграции."""
    client_id: Mapped[UUID]
    """identity.users: FK в миграции; кого просим."""
    performer_id: Mapped[UUID]
    completed_at: Mapped[datetime]
    reminded_at: Mapped[datetime | None]
    last_call_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index(
            "ix_review_requests_completed_at",
            "completed_at",
            postgresql_where=text("last_call_at IS NULL"),
        ),
        Index("ix_review_requests_client_id", "client_id"),
        Index("ix_review_requests_performer_id", "performer_id"),
    )
