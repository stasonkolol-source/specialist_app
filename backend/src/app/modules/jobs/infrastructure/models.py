"""ORM-модели jobs (ARCHITECTURE §7.3, миграции jobs_0001–0010): заявки, их фото, история
статусов, скрытые и сохранённые исполнителями заявки, отклики, шаблоны откликов, приглашения,
подписки на новые заявки и совпадения заявок с подписками (5.7).

FK на identity.users, catalog.categories, geo.cities, geo.districts, media.assets и
specialists.profiles объявлены только в миграции: MetaData модуля не знает чужих таблиц
(modules/README.md). `tag_ids`, `verified_only` и `search_vector` — задел ленты и поиска
заявок (5.3).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.jobs.domain.alert import MAX_RADIUS_M, MIN_RADIUS_M, AlertDelivery
from app.modules.jobs.domain.job import (
    MAX_DESCRIPTION,
    MAX_TITLE,
    MIN_TITLE,
    ActorKind,
    BudgetType,
    BudgetUnit,
    CloseReason,
    JobStatus,
    Urgency,
    Visibility,
)
from app.modules.jobs.domain.response import (
    MAX_AVAILABILITY,
    MAX_MESSAGE,
    ResponsePriceType,
    ResponseReview,
    ResponseStatus,
)
from app.modules.jobs.domain.template import MAX_TEMPLATE_TITLE
from app.platform.db.base import (
    ModelBase,
    SoftDeleteMixin,
    TimestampsMixin,
    UuidPkMixin,
    VersionMixin,
    module_metadata,
)
from app.platform.db.types import GeoPointType, rsd_only, str_enum
from app.platform.kernel.geo import GeoPoint

SCHEMA = "jobs"
metadata = module_metadata(SCHEMA)
PUBLISHED = text("status = 'published'")


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class JobRow(UuidPkMixin, TimestampsMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "jobs"

    client_id: Mapped[UUID]
    """identity.users: FK fk_jobs_client_id_users — в миграции jobs_0001."""
    status: Mapped[JobStatus] = mapped_column(
        str_enum(JobStatus, "status"), server_default=JobStatus.DRAFT.value
    )
    visibility: Mapped[Visibility] = mapped_column(
        str_enum(Visibility, "visibility"), server_default=Visibility.PUBLIC.value
    )
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    content_lang: Mapped[str] = mapped_column(String(8))
    category_id: Mapped[int] = mapped_column(Integer)
    """catalog.categories: FK в миграции."""
    category_path: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    """Копия categories.path: фильтр «категория с потомками» (лента 5.3)."""
    tag_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default=text("'{}'"))
    urgency: Mapped[Urgency] = mapped_column(str_enum(Urgency, "urgency"))
    preferred_from: Mapped[datetime | None]
    preferred_to: Mapped[datetime | None]
    budget_type: Mapped[BudgetType] = mapped_column(str_enum(BudgetType, "budget_type"))
    budget_min: Mapped[int | None] = mapped_column(BigInteger)
    """Пара."""
    budget_max: Mapped[int | None] = mapped_column(BigInteger)
    budget_unit: Mapped[BudgetUnit] = mapped_column(
        str_enum(BudgetUnit, "budget_unit"), server_default=BudgetUnit.WORK.value
    )
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'RSD'"))
    verified_only: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    city_id: Mapped[int] = mapped_column(Integer)
    """geo.cities: FK в миграции."""
    district_id: Mapped[int | None] = mapped_column(Integer)
    """geo.districts: FK в миграции."""
    point_exact: Mapped[GeoPoint | None] = mapped_column(GeoPointType)
    """Точная точка — только выбранному исполнителю (§7.6)."""
    point_public: Mapped[GeoPoint | None] = mapped_column(GeoPointType)
    """Смещённая на 300–500 м точка — для ленты, карты и радиуса."""
    address_private: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(8)), server_default=text("'{}'"))
    max_responses: Mapped[int] = mapped_column(SmallInteger, server_default=text("5"))
    responses_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    extensions_count: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    views_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    notified_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    """Скольким подписчикам заявка подошла (jobs_0010): сразу или в подборке — «уведомили N
    исполнителей» владельцу (S21, S23)."""
    responses_seen_at: Mapped[datetime | None]
    """Клиент открыл отклики на S23 (jobs_0008): позже прошедшие проверку — «новые»."""
    revision: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    """Редакция содержимого (jobs_0011, domain Job.revision): ETag и версия для модерации."""
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)
    source: Mapped[str] = mapped_column(String(16), server_default=text("'tma'"))
    moderation_note: Mapped[str | None] = mapped_column(String(64))
    selected_response_id: Mapped[UUID | None]
    published_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]
    expiry_reminded_at: Mapped[datetime | None]
    """Напомнили о конце текущего срока (`job.expiring`, миграция jobs_0002)."""
    closed_at: Mapped[datetime | None]
    close_reason: Mapped[CloseReason | None] = mapped_column(str_enum(CloseReason, "close_reason"))

    __table_args__ = (
        CheckConstraint(
            f"char_length(title) BETWEEN {MIN_TITLE} AND {MAX_TITLE}", name="title_length"
        ),
        CheckConstraint(
            f"char_length(description) <= {MAX_DESCRIPTION}", name="description_length"
        ),
        CheckConstraint("budget_type = 'negotiable' OR budget_min IS NOT NULL", name="budget_set"),
        rsd_only("currency"),
        Index(
            "ix_jobs_client_id_created_at",
            "client_id",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_jobs_city_id_published_at",
            "city_id",
            "published_at",
            "id",
            postgresql_where=PUBLISHED,
        ),
        Index("ix_jobs_expires_at", "expires_at", postgresql_where=PUBLISHED),
        # «N заявок за неделю» подписки S18 (5.7): опубликованные за неделю, и уже закрытые
        Index(
            "ix_jobs_city_id_published_at_any",
            "city_id",
            "published_at",
            postgresql_where=text("published_at IS NOT NULL"),
        ),
        # «M заявок» в блоке клиента S15: сколько его заявок когда-либо публиковалось
        Index(
            "ix_jobs_client_id_published",
            "client_id",
            postgresql_where=text("published_at IS NOT NULL"),
        ),
        # лента 5.3: радиус от точки зрителя и «категория с подкатегориями» (&&)
        Index(
            "ix_jobs_point_public",
            "point_public",
            postgresql_using="gist",
            postgresql_where=PUBLISHED,
        ),
        Index(
            "ix_jobs_category_path",
            "category_path",
            postgresql_using="gin",
            postgresql_where=PUBLISHED,
        ),
    )


class JobMediaRow(Base):
    """Фото заявки по порядку (S20b)."""

    __tablename__ = "job_media"

    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    media_id: Mapped[UUID] = mapped_column(primary_key=True)
    """media.assets: FK в миграции."""
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


class StatusHistoryRow(Base):
    """Переход статуса заявки (§7.10): кто, когда и почему."""

    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24))
    actor_id: Mapped[UUID | None]
    actor_kind: Mapped[ActorKind] = mapped_column(str_enum(ActorKind, "actor_kind"))
    reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_status_history_job_id", "job_id"),)


class HiddenJobRow(Base):
    """«Не подходит» (S15): заявка скрыта из ленты исполнителя (миграция jobs_0003)."""

    __tablename__ = "hidden_jobs"

    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    """identity.users: FK в миграции."""
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SavedJobRow(Base):
    """Сохранённая заявка (сердечко S15, сегмент «Задачи» S12; миграция jobs_0004)."""

    __tablename__ = "saved_jobs"

    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    """identity.users: FK в миграции."""
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class InviteRow(Base):
    """Приглашение профиля в заявку или прямой запрос ему (S21, S23, S08; миграция jobs_0007)."""

    __tablename__ = "invites"

    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    profile_id: Mapped[UUID] = mapped_column(primary_key=True)
    """specialists.profiles: FK в миграции."""
    performer_id: Mapped[UUID]
    """identity.users — владелец профиля: FK в миграции."""
    invited_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_invites_performer_id_job_id", "performer_id", "job_id"),)


class ResponseRow(TimestampsMixin, SoftDeleteMixin, Base):
    """Отклик исполнителя (§7.9, миграция jobs_0005): подагрегат заявки, пишется вместе с ней."""

    __tablename__ = "responses"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    performer_id: Mapped[UUID]
    """identity.users: FK в миграции."""
    profile_id: Mapped[UUID | None]
    """specialists.profiles: FK в миграции; без профиля — подработка."""
    status: Mapped[ResponseStatus] = mapped_column(
        str_enum(ResponseStatus, "status"), server_default=ResponseStatus.SUBMITTED.value
    )
    message: Mapped[str] = mapped_column(Text)
    price_type: Mapped[ResponsePriceType] = mapped_column(str_enum(ResponsePriceType, "price_type"))
    price_amount: Mapped[int | None] = mapped_column(BigInteger)
    """Пара; у договорной — нет."""
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'RSD'"))
    availability_note: Mapped[str | None] = mapped_column(Text)
    template_id: Mapped[UUID | None]
    """jobs.response_templates (5.5): отклик в один тап из шаблона."""
    review: Mapped[ResponseReview] = mapped_column(
        str_enum(ResponseReview, "review"), server_default=ResponseReview.PENDING.value
    )
    """Проверка текста модерацией: клиент видит только `clear`."""
    revision: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    viewed_at: Mapped[datetime | None]
    decided_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(f"char_length(message) BETWEEN 1 AND {MAX_MESSAGE}", name="message_length"),
        CheckConstraint(
            f"char_length(availability_note) <= {MAX_AVAILABILITY}",
            name="availability_note_length",
        ),
        CheckConstraint(
            "(price_type = 'negotiable') = (price_amount IS NULL)", name="price_amount_set"
        ),
        rsd_only("currency"),
        # один отклик на заявку от исполнителя; отозванный не повторяется
        Index(
            "uq_responses_job_id_performer_id",
            "job_id",
            "performer_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_responses_job_id_created_at", "job_id", "created_at"),
        Index("ix_responses_performer_id_created_at", "performer_id", text("created_at DESC")),
    )


class ResponseTemplateRow(TimestampsMixin, SoftDeleteMixin, Base):
    """Шаблон отклика (S57, миграция jobs_0006): не больше двух у исполнителя, 0 — основной."""

    __tablename__ = "response_templates"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID]
    """identity.users: FK в миграции."""
    title: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    price_type: Mapped[ResponsePriceType] = mapped_column(str_enum(ResponsePriceType, "price_type"))
    price_amount: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'RSD'"))
    availability_note: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))

    __table_args__ = (
        CheckConstraint(
            f"char_length(title) BETWEEN 1 AND {MAX_TEMPLATE_TITLE}", name="title_length"
        ),
        CheckConstraint(f"char_length(message) BETWEEN 1 AND {MAX_MESSAGE}", name="message_length"),
        CheckConstraint(
            f"char_length(availability_note) <= {MAX_AVAILABILITY}",
            name="availability_note_length",
        ),
        CheckConstraint(
            "(price_type = 'negotiable') = (price_amount IS NULL)", name="price_amount_set"
        ),
        rsd_only("currency"),
        Index(
            "ix_response_templates_user_id_position",
            "user_id",
            "position",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class AlertRow(TimestampsMixin, Base):
    """Подписка на новые заявки (S18, S19; ARCHITECTURE §7.3, миграция jobs_0010). Простая
    запись: удаляется сразу, истории нет."""

    __tablename__ = "alerts"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID]
    """identity.users: FK в миграции."""
    category_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    """Выбранные узлы каталога: заявка подходит, если её путь (`category_path`) их задевает."""
    city_id: Mapped[int] = mapped_column(Integer)
    """geo.cities: FK в миграции."""
    district_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), server_default=text("'{}'"))
    """Пусто и нет точки — весь город."""
    center: Mapped[GeoPoint | None] = mapped_column(GeoPointType)
    """Точка подписчика для радиуса — только ему: наружу не отдаётся."""
    radius_m: Mapped[int | None] = mapped_column(Integer)
    min_budget: Mapped[int | None] = mapped_column(BigInteger)
    """Пара."""
    urgencies: Mapped[list[str]] = mapped_column(ARRAY(String(16)), server_default=text("'{}'"))
    languages: Mapped[list[str]] = mapped_column(ARRAY(String(8)), server_default=text("'{}'"))
    delivery: Mapped[AlertDelivery] = mapped_column(
        str_enum(AlertDelivery, "delivery"), server_default=AlertDelivery.INSTANT.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    paused_until: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(f"radius_m BETWEEN {MIN_RADIUS_M} AND {MAX_RADIUS_M}", name="radius_range"),
        CheckConstraint("(center IS NULL) = (radius_m IS NULL)", name="radius_with_center"),
        CheckConstraint(
            "cardinality(district_ids) = 0 OR center IS NULL", name="districts_or_radius"
        ),
        CheckConstraint("cardinality(category_ids) > 0", name="has_categories"),
        Index("ix_alerts_user_id", "user_id"),
        # матчинг §9.6: категории по GIN, круг — по GiST центра с потолком радиуса
        Index(
            "ix_alerts_category_ids",
            "category_ids",
            postgresql_using="gin",
            postgresql_where=text("is_active"),
        ),
        Index(
            "ix_alerts_center",
            "center",
            postgresql_using="gist",
            postgresql_where=text("is_active AND center IS NOT NULL"),
        ),
    )


class AlertMatchRow(Base):
    """Заявка подошла подписчику (миграция jobs_0010): одна строка на пару «заявка — человек».
    Сразу (`instant`) — B1 уже поставлен, подборкой (`digest`) — ждёт `jobs.alert_digests`.
    Строки за последние сутки — лимит частоты B1; старше месяца удаляются."""

    __tablename__ = "alert_matches"

    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    """identity.users: FK в миграции."""
    alert_id: Mapped[UUID] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"))
    delivery: Mapped[AlertDelivery] = mapped_column(str_enum(AlertDelivery, "delivery"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    digested_at: Mapped[datetime | None]

    __table_args__ = (
        Index("ix_alert_matches_user_id_created_at", "user_id", "created_at"),
        Index("ix_alert_matches_alert_id", "alert_id"),
        Index(
            "ix_alert_matches_pending",
            "user_id",
            postgresql_where=text("delivery = 'digest' AND digested_at IS NULL"),
        ),
    )
