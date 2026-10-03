"""ORM-модели deals (ARCHITECTURE §7.3, миграции deals_0001–0003): сделки, история их статусов и
споры (6.1c).

FK на identity.users, specialists.profiles и catalog.categories объявлены только в миграции:
MetaData модуля не знает чужих таблиц (modules/README.md). Ссылки вверх по DAG — `job_id`,
`response_id`, `conversation_id` — без FK; кейс модерации спора moderation находит сам (кейс
объекта `dispute`).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.deals.domain.deal import (
    MAX_TITLE,
    ActorKind,
    DealCancelReason,
    DealOrigin,
    DealPriceType,
    DealStatus,
)
from app.modules.deals.domain.dispute import (
    MAX_REASON_CODE,
    MAX_TEXT,
    DisputeKind,
    DisputeOutcome,
    DisputeStatus,
)
from app.platform.db.base import (
    ModelBase,
    TimestampsMixin,
    UuidPkMixin,
    VersionMixin,
    module_metadata,
)
from app.platform.db.types import rsd_only, str_enum

SCHEMA = "deals"
metadata = module_metadata(SCHEMA)
AGREED = text("status = 'agreed'")
PROPOSED = text("status = 'proposed'")


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class DealRow(UuidPkMixin, TimestampsMixin, VersionMixin, Base):
    __tablename__ = "deals"

    client_id: Mapped[UUID]
    """identity.users: FK в миграции deals_0001."""
    performer_id: Mapped[UUID]
    """identity.users: FK в миграции."""
    profile_id: Mapped[UUID | None]
    """specialists.profiles: FK в миграции."""
    origin: Mapped[DealOrigin] = mapped_column(str_enum(DealOrigin, "origin"))
    job_id: Mapped[UUID | None]
    response_id: Mapped[UUID | None] = mapped_column(unique=True)
    """Один отклик — одна сделка: повторный выбор того же отклика не создаст вторую."""
    conversation_id: Mapped[UUID | None]
    title_snapshot: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(Integer)
    """catalog.categories: FK в миграции."""
    status: Mapped[DealStatus] = mapped_column(
        str_enum(DealStatus, "status"), server_default=DealStatus.AGREED.value
    )
    proposed_by: Mapped[UUID | None]
    price_type: Mapped[DealPriceType | None] = mapped_column(str_enum(DealPriceType, "price_type"))
    agreed_price: Mapped[int | None] = mapped_column(BigInteger)
    """Пара."""
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'RSD'"))
    scheduled_at: Mapped[datetime | None]
    agreed_at: Mapped[datetime | None]
    client_confirmed_at: Mapped[datetime | None]
    """Клиент отметил «Работа выполнена»."""
    performer_confirmed_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]
    cancelled_by: Mapped[UUID | None]
    cancel_reason: Mapped[DealCancelReason | None] = mapped_column(
        str_enum(DealCancelReason, "cancel_reason")
    )
    reminded_at: Mapped[datetime | None]
    """Сторонам напомнили о времени сделки (deals_0002)."""
    completion_prompted_at: Mapped[datetime | None]
    """Сторонам задали вопрос «Работа выполнена?» (deals_0002)."""

    __table_args__ = (
        CheckConstraint(
            f"char_length(title_snapshot) BETWEEN 1 AND {MAX_TITLE}", name="title_length"
        ),
        CheckConstraint("client_id <> performer_id", name="two_parties"),
        CheckConstraint(
            "origin <> 'job_response' OR (job_id IS NOT NULL AND response_id IS NOT NULL)",
            name="response_origin_refs",
        ),
        rsd_only("currency"),
        Index("ix_deals_client_id_created_at", "client_id", "created_at"),
        Index("ix_deals_performer_id_created_at", "performer_id", "created_at"),
        Index("ix_deals_job_id", "job_id", postgresql_where=text("job_id IS NOT NULL")),
        # проходы периодических задач сроков (6.1b)
        Index("ix_deals_agreed_scheduled_at", "scheduled_at", postgresql_where=AGREED),
        Index("ix_deals_agreed_agreed_at", "agreed_at", postgresql_where=AGREED),
        Index("ix_deals_proposed_created_at", "created_at", postgresql_where=PROPOSED),
    )


class StatusHistoryRow(Base):
    """Переход статуса сделки (§7.10): кто, когда и почему; создание — без `from_status`."""

    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deals.id"))
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[UUID | None]
    actor_kind: Mapped[ActorKind] = mapped_column(str_enum(ActorKind, "actor_kind"))
    reason: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_status_history_deal_id", "deal_id"),)


ACTIVE_DISPUTE = "status IN ('open', 'answered', 'no_response')"
"""Идущий спор (domain/dispute.py ACTIVE): предикат частичных индексов."""


class DisputeRow(UuidPkMixin, TimestampsMixin, VersionMixin, Base):
    """Спор по сделке (domain/dispute.py); `created_at` — когда открыт. Доказательства — id
    файлов media `dispute` (приватный бакет) у каждой стороны."""

    __tablename__ = "disputes"

    deal_id: Mapped[UUID] = mapped_column(ForeignKey("deals.id"))
    opened_by: Mapped[UUID]
    """identity.users: FK в миграции deals_0003."""
    respondent_id: Mapped[UUID]
    """identity.users: FK в миграции."""
    kind: Mapped[DisputeKind] = mapped_column(str_enum(DisputeKind, "kind"))
    description: Mapped[str] = mapped_column(Text)
    media_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), server_default=text("'{}'"))
    respond_by: Mapped[datetime]
    status: Mapped[DisputeStatus] = mapped_column(
        str_enum(DisputeStatus, "status"), server_default=DisputeStatus.OPEN.value
    )
    response: Mapped[str | None] = mapped_column(Text)
    response_media_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), server_default=text("'{}'"))
    responded_at: Mapped[datetime | None]
    unanswered_at: Mapped[datetime | None]
    withdrawn_at: Mapped[datetime | None]
    outcome: Mapped[DisputeOutcome | None] = mapped_column(str_enum(DisputeOutcome, "outcome"))
    reason_code: Mapped[str | None] = mapped_column(String(MAX_REASON_CODE))
    resolved_by: Mapped[UUID | None]
    """Модератор (identity.users): FK в миграции."""
    resolved_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(
            f"char_length(description) BETWEEN 1 AND {MAX_TEXT}", name="description_length"
        ),
        CheckConstraint(f"char_length(response) <= {MAX_TEXT}", name="response_length"),
        CheckConstraint("opened_by <> respondent_id", name="two_parties"),
        CheckConstraint(
            "(status = 'resolved') = (outcome IS NOT NULL AND resolved_at IS NOT NULL)",
            name="resolved_with_outcome",
        ),
        # один идущий спор на сделку: следующий — после отзыва или решения
        Index(
            "uq_disputes_deal_id_active",
            "deal_id",
            unique=True,
            postgresql_where=text(ACTIVE_DISPUTE),
        ),
        Index("ix_disputes_deal_id_created_at", "deal_id", "created_at"),
        # проход `deals.dispute_response_sla`: ждут ответа — по сроку
        Index(
            "ix_disputes_open_respond_by", "respond_by", postgresql_where=text("status = 'open'")
        ),
        # legal hold удаления аккаунта: стороны идущих споров
        Index("ix_disputes_opened_by_active", "opened_by", postgresql_where=text(ACTIVE_DISPUTE)),
        Index(
            "ix_disputes_respondent_id_active",
            "respondent_id",
            postgresql_where=text(ACTIVE_DISPUTE),
        ),
    )
