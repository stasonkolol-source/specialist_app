"""moderation_0002: кейсы, ступени санкций, сигналы риска, жалобы (DEVELOPMENT_PLAN 2.5a).

- `cases` — единица работы модератора: очередь (safety/fraud/premod/appeals), срок SLA,
  поводы (`evidence`), файлы-доказательства под legal hold (`media_ids`), решение с кодом
  причины и версией политики. Один открытый кейс на объект — `uq_cases_entity_open`.
- `sanctions` — ступени лестницы (предупреждение, страйки, бан, приостановка); сама санкция
  на аккаунт — в identity.restrictions.
- `risk_signals` — сигналы риска; `dedupe_key` — один факт пишется один раз.
- `reports` — жалобы пользователей по DDL архитектуры, с `due_at` (задел v1); приём — 4.7.
FK на identity.users и identity.restrictions — вниз по DAG модулей (ARCHITECTURE §5.2).
Таблицы новые и пустые.

Ревизия: moderation_0002 (2026-09-30 21:10:00.000000+00:00)
Предыдущая: media_0004

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "moderation_0002"
down_revision: str | Sequence[str] | None = "media_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "moderation"
OPEN_CASE = "status IN ('pending', 'in_review', 'escalated')"
ENTITY_TYPES = "'user', 'profile', 'job', 'response', 'review', 'message', 'media'"


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("queue", sa.String(length=15), nullable=False),
        sa.Column("entity_type", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(length=19), nullable=False),
        sa.Column("status", sa.String(length=17), server_default="pending", nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("media_ids", postgresql.ARRAY(sa.Uuid()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("appeal_of", sa.Uuid(), nullable=True),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("policy_version", sa.String(length=32), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("queue IN ('safety', 'fraud', 'premod', 'appeals')", name=op.f("ck_cases_queue")),
        sa.CheckConstraint(f"entity_type IN ({ENTITY_TYPES})", name=op.f("ck_cases_entity_type")),
        sa.CheckConstraint(
            "trigger IN ('new_content', 'edit', 'report', 'auto_flag', 'appeal')",
            name=op.f("ck_cases_trigger"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_review', 'escalated', 'approved', 'rejected')",
            name=op.f("ck_cases_status"),
        ),
        sa.CheckConstraint(
            "(status IN ('approved', 'rejected')) = (decided_at IS NOT NULL)",
            name=op.f("ck_cases_decided_when_closed"),
        ),
        sa.CheckConstraint(
            "status <> 'rejected' OR reason_code IS NOT NULL", name=op.f("ck_cases_rejected_reason")
        ),
        sa.ForeignKeyConstraint(["appeal_of"], ["moderation.cases.id"], name=op.f("fk_cases_appeal_of_cases")),
        sa.ForeignKeyConstraint(["subject_id"], ["identity.users.id"], name=op.f("fk_cases_subject_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cases")),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_cases_entity_open", "cases", ["entity_type", "entity_id"], unique=True,
        schema=SCHEMA, postgresql_where=sa.text(OPEN_CASE),
    )
    op.create_index(
        "ix_cases_queue_due_at_open", "cases", ["queue", "due_at"], unique=False,
        schema=SCHEMA, postgresql_where=sa.text(OPEN_CASE),
    )
    op.create_index(
        "ix_cases_media_ids_open", "cases", ["media_ids"], unique=False, schema=SCHEMA,
        postgresql_using="gin", postgresql_where=sa.text(OPEN_CASE),
    )
    op.create_index("ix_cases_subject_id", "cases", ["subject_id"], unique=False, schema=SCHEMA)
    op.create_index(
        "ix_cases_decided_at", "cases", ["decided_at"], unique=False, schema=SCHEMA,
        postgresql_where=sa.text("decided_at IS NOT NULL"),
    )

    op.create_table(
        "sanctions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("step", sa.String(length=18), nullable=False),
        sa.Column("restriction_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint(
            "step IN ('warning', 'strike_1', 'strike_2', 'ban', 'suspension')",
            name=op.f("ck_sanctions_step"),
        ),
        sa.ForeignKeyConstraint(["case_id"], ["moderation.cases.id"], name=op.f("fk_sanctions_case_id_cases")),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], name=op.f("fk_sanctions_user_id_users")),
        sa.ForeignKeyConstraint(
            ["restriction_id"], ["identity.restrictions.id"],
            name=op.f("fk_sanctions_restriction_id_restrictions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sanctions")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_sanctions_user_id_created_at", "sanctions", ["user_id", sa.text("created_at DESC")],
        unique=False, schema=SCHEMA,
    )

    op.create_table(
        "risk_signals",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("signal", sa.String(length=35), nullable=False),
        sa.Column("weight", sa.REAL(), server_default=sa.text("1"), nullable=False),
        sa.Column("ref_type", sa.String(length=32), nullable=True),
        sa.Column("ref_id", sa.Uuid(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "signal IN ('rate_limit_exceeded', 'report_confirmed', 'contact_leak', "
            "'prepayment_request', 'reregistered_after_deletion')",
            name=op.f("ck_risk_signals_signal"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], name=op.f("fk_risk_signals_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_signals")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_risk_signals_dedupe_key")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_risk_signals_user_id_created_at", "risk_signals", ["user_id", sa.text("created_at DESC")],
        unique=False, schema=SCHEMA,
    )

    op.create_table(
        "reports",
        sa.Column("reporter_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=21), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("is_legal_notice", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint(f"target_type IN ({ENTITY_TYPES})", name=op.f("ck_reports_target_type")),
        sa.CheckConstraint(
            "reason IN ('spam', 'fraud', 'prohibited', 'offensive', 'fake_profile', 'no_show', "
            "'personal_data', 'defamation', 'copyright', 'illegal', 'other')",
            name=op.f("ck_reports_reason"),
        ),
        sa.CheckConstraint("status IN ('open', 'resolved', 'rejected')", name=op.f("ck_reports_status")),
        sa.ForeignKeyConstraint(["case_id"], ["moderation.cases.id"], name=op.f("fk_reports_case_id_cases")),
        sa.ForeignKeyConstraint(["reporter_id"], ["identity.users.id"], name=op.f("fk_reports_reporter_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reports")),
        sa.UniqueConstraint(
            "reporter_id", "target_type", "target_id",
            name=op.f("uq_reports_reporter_id_target_type_target_id"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_reports_due_at_legal_open", "reports", ["due_at"], unique=False, schema=SCHEMA,
        postgresql_where=sa.text("status = 'open' AND is_legal_notice"),
    )


def downgrade() -> None:
    op.drop_table("reports", schema=SCHEMA)
    op.drop_table("risk_signals", schema=SCHEMA)
    op.drop_table("sanctions", schema=SCHEMA)
    op.drop_table("cases", schema=SCHEMA)
