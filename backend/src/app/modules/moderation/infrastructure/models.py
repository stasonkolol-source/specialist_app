"""ORM-модели moderation (ARCHITECTURE §7.3, миграции moderation_0001–0005).

Словарь контент-правил (2.4); кейсы, ступени санкций, сигналы риска и жалобы (2.5a).
FK на identity.users и identity.restrictions объявлены только в миграции moderation_0002:
MetaData модуля не знает чужих таблиц (modules/README.md).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.moderation.domain.cases import MAX_REASON_CODE, CaseStatus, CaseTrigger, EntityType
from app.modules.moderation.domain.queues import Queue
from app.modules.moderation.domain.reports import ReportReason, ReportStatus
from app.modules.moderation.domain.risk import RiskSignalKind
from app.modules.moderation.domain.rules import (
    MAX_PATTERN,
    RuleAction,
    RuleCategory,
    RuleKind,
    RuleLanguage,
)
from app.modules.moderation.domain.sanctions import SanctionStep
from app.platform.db.base import ModelBase, TimestampsMixin, UuidPkMixin, module_metadata
from app.platform.db.types import str_enum

SCHEMA = "moderation"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


IMPORT_LOCK = 0x6D6F645F72756C65
"""pg_advisory_xact_lock словаря контент-правил: «mod_rule» в hex. Берут импорт `cli seed`
(infrastructure/rules.py) и правка в админке (admin/views.py), чтобы не перетереть друг друга."""


class RuleOrigin(StrEnum):
    SEED = "seed"
    """Из seeds/moderation/content_rules.yaml: `cli seed` создаёт, меняет и выключает."""
    ADMIN = "admin"
    """Завела админка (2.7b): сид такие строки не трогает."""


class ContentRuleRow(TimestampsMixin, Base):
    """Стоп-слово, регулярка по скелету или домен (domain/rules.py)."""

    __tablename__ = "content_rules"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    pattern: Mapped[str] = mapped_column(String(MAX_PATTERN))
    kind: Mapped[RuleKind] = mapped_column(str_enum(RuleKind, "kind"))
    lang: Mapped[RuleLanguage | None] = mapped_column(str_enum(RuleLanguage, "lang"))
    action: Mapped[RuleAction] = mapped_column(str_enum(RuleAction, "action"))
    category: Mapped[RuleCategory] = mapped_column(str_enum(RuleCategory, "category"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    origin: Mapped[RuleOrigin] = mapped_column(
        str_enum(RuleOrigin, "origin"), server_default=RuleOrigin.ADMIN.value
    )

    __table_args__ = (
        UniqueConstraint("kind", "pattern"),
        # регулярки — только из сида, прошедшего ревью (миграция moderation_0001)
        CheckConstraint("kind <> 'regex' OR origin = 'seed'", name="regex_from_seed"),
    )


OPEN_CASE = "status IN ('pending', 'in_review', 'escalated')"
"""Открытый кейс (domain/cases.py OPEN): предикат частичных индексов."""


class CaseRow(TimestampsMixin, Base):
    """Кейс модерации (domain/cases.py); `created_at` — когда открыт."""

    __tablename__ = "cases"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    queue: Mapped[Queue] = mapped_column(str_enum(Queue, "queue"))
    entity_type: Mapped[EntityType] = mapped_column(str_enum(EntityType, "entity_type"))
    entity_id: Mapped[UUID]
    subject_id: Mapped[UUID]
    """identity.users: FK fk_cases_subject_id_users — в миграции moderation_0002."""
    trigger: Mapped[CaseTrigger] = mapped_column(str_enum(CaseTrigger, "trigger"))
    status: Mapped[CaseStatus] = mapped_column(
        str_enum(CaseStatus, "status"), server_default=CaseStatus.PENDING.value
    )
    due_at: Mapped[datetime]
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    media_ids: Mapped[list[UUID]] = mapped_column(ARRAY(Uuid), server_default=text("'{}'"))
    appeal_of: Mapped[UUID | None] = mapped_column(ForeignKey("cases.id"))
    assigned_to: Mapped[UUID | None]
    decided_by: Mapped[UUID | None]
    reason_code: Mapped[str | None] = mapped_column(String(MAX_REASON_CODE))
    policy_version: Mapped[str | None] = mapped_column(String(32))
    decided_at: Mapped[datetime | None]
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # один открытый кейс на объект: второй повод дописывается в него; апелляция (2.5b) —
        # отдельно, по объекту может идти и новый кейс
        Index(
            "uq_cases_entity_open",
            "entity_type",
            "entity_id",
            unique=True,
            postgresql_where=text(f"{OPEN_CASE} AND appeal_of IS NULL"),
        ),
        # апелляция на решение — одна: итог окончательный
        Index(
            "uq_cases_appeal_of",
            "appeal_of",
            unique=True,
            postgresql_where=text("appeal_of IS NOT NULL"),
        ),
        Index("ix_cases_queue_due_at_open", "queue", "due_at", postgresql_where=text(OPEN_CASE)),
        # legal hold: файлы открытых кейсов (media.purge_deleted)
        Index(
            "ix_cases_media_ids_open",
            "media_ids",
            postgresql_using="gin",
            postgresql_where=text(OPEN_CASE),
        ),
        Index("ix_cases_subject_id", "subject_id"),
        Index("ix_cases_decided_at", "decided_at", postgresql_where=text("decided_at IS NOT NULL")),
        CheckConstraint(
            "(status IN ('approved', 'rejected')) = (decided_at IS NOT NULL)",
            name="decided_when_closed",
        ),
        CheckConstraint("status <> 'rejected' OR reason_code IS NOT NULL", name="rejected_reason"),
    )


class SanctionRow(UuidPkMixin, Base):
    """Ступень лестницы санкций по решению кейса (domain/sanctions.py)."""

    __tablename__ = "sanctions"

    user_id: Mapped[UUID]
    """identity.users: FK fk_sanctions_user_id_users — в миграции moderation_0002."""
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"))
    step: Mapped[SanctionStep] = mapped_column(str_enum(SanctionStep, "step"))
    restriction_id: Mapped[UUID | None]
    """identity.restrictions: FK fk_sanctions_restriction_id_restrictions — в миграции."""
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime | None]
    """Ступень сгорает (180 дней); бан и приостановка — None."""
    revoked_at: Mapped[datetime | None]
    """Отменена апелляцией (2.5b): в лестнице не считается."""

    __table_args__ = (Index("ix_sanctions_user_id_created_at", "user_id", text("created_at DESC")),)


class RiskSignalRow(Base):
    """Сигнал риска (domain/risk.py)."""

    __tablename__ = "risk_signals"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[UUID]
    """identity.users: FK fk_risk_signals_user_id_users — в миграции moderation_0002."""
    signal: Mapped[RiskSignalKind] = mapped_column(str_enum(RiskSignalKind, "signal"))
    weight: Mapped[float] = mapped_column(REAL, server_default=text("1"))
    ref_type: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[UUID | None]
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    dedupe_key: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint("dedupe_key"),
        Index("ix_risk_signals_user_id_created_at", "user_id", text("created_at DESC")),
    )


OPEN_REPORT = "uq_reports_open"
"""Одна открытая жалоба человека на объект (moderation_0005): повтор — та же жалоба."""


class ReportRow(UuidPkMixin, Base):
    """Жалоба пользователя (domain/reports.py); приём — `POST /reports` (4.7)."""

    __tablename__ = "reports"

    reporter_id: Mapped[UUID]
    """identity.users: FK fk_reports_reporter_id_users — в миграции moderation_0002."""
    target_type: Mapped[EntityType] = mapped_column(str_enum(EntityType, "target_type"))
    target_id: Mapped[UUID]
    reason: Mapped[ReportReason] = mapped_column(str_enum(ReportReason, "reason"))
    comment: Mapped[str | None] = mapped_column(Text)
    is_legal_notice: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    """Заявление третьего лица о незаконном контенте (ст. 20 ZET)."""
    due_at: Mapped[datetime | None]
    """Срок заявления третьего лица: +2 рабочих дня — таймер v1 (ADR-0018)."""
    case_id: Mapped[UUID | None] = mapped_column(ForeignKey("cases.id"))
    status: Mapped[ReportStatus] = mapped_column(
        str_enum(ReportStatus, "status"), server_default=ReportStatus.OPEN.value
    )
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[UUID | None]
    resolved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index(
            OPEN_REPORT,
            "reporter_id",
            "target_type",
            "target_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_reports_case_id", "case_id"),
        Index(
            "ix_reports_due_at_legal_open",
            "due_at",
            postgresql_where=text("status = 'open' AND is_legal_notice"),
        ),
    )
