"""deals_0003: споры по сделкам (DEVELOPMENT_PLAN 6.1c; ARCHITECTURE §7.9, §14.4).

`deals.disputes` — спор стороны по идущей сделке: что случилось, описание, фото-доказательства
(id файлов media `dispute` у каждой стороны — массивом, как `moderation.cases.media_ids`),
48 ч на ответ второй стороны, ответ, пометка «нет ответа», отзыв и решение модератора. Один
идущий спор на сделку — частичный уникальный индекс. Таблица новая: индексы — обычные.

`deals.cancel_reason` принимает `dispute` — отмену модератором по итогам спора: CHECK —
надмножество старого, NOT VALID и VALIDATE вне транзакции миграции (как notifications_0004).
Откат удаляет споры и возвращает старый CHECK; сделки, отменённые по спору, откат не трогает —
VALIDATE тогда упадёт (ADR-0005: данные не теряем).

Ревизия: deals_0003 (2026-10-03 12:00:00.000000+00:00)
Предыдущая: jobs_0009

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

revision: str = "deals_0003"
down_revision: str | Sequence[str] | None = "jobs_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "deals"
ACTIVE = "status IN ('open', 'answered', 'no_response')"
CANCEL_REASONS_OLD = (
    "'plans_changed', 'no_agreement', 'no_contact', 'other', 'expired', 'account_deleted'"
)
CANCEL_REASONS_NEW = f"{CANCEL_REASONS_OLD}, 'dispute'"
CANCEL_CHECK = "ck_deals_cancel_reason"


def upgrade() -> None:
    op.create_table(
        "disputes",
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("opened_by", sa.Uuid(), nullable=False),
        sa.Column("respondent_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "media_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("respond_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=19), server_default="open", nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column(
            "response_media_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unanswered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=17), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('no_show', 'quality', 'prepayment_taken', 'damage', 'safety', 'other')",
            name=op.f("ck_disputes_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'answered', 'no_response', 'resolved', 'withdrawn')",
            name=op.f("ck_disputes_status"),
        ),
        sa.CheckConstraint(
            "outcome IN ('completed', 'cancelled')", name=op.f("ck_disputes_outcome")
        ),
        sa.CheckConstraint(
            "char_length(description) BETWEEN 1 AND 2000",
            name=op.f("ck_disputes_description_length"),
        ),
        sa.CheckConstraint(
            "char_length(response) <= 2000", name=op.f("ck_disputes_response_length")
        ),
        sa.CheckConstraint("opened_by <> respondent_id", name=op.f("ck_disputes_two_parties")),
        sa.CheckConstraint(
            "(status = 'resolved') = (outcome IS NOT NULL AND resolved_at IS NOT NULL)",
            name=op.f("ck_disputes_resolved_with_outcome"),
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.deals.id"], name=op.f("fk_disputes_deal_id_deals")
        ),
        sa.ForeignKeyConstraint(
            ["opened_by"], ["identity.users.id"], name=op.f("fk_disputes_opened_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["respondent_id"],
            ["identity.users.id"],
            name=op.f("fk_disputes_respondent_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["identity.users.id"], name=op.f("fk_disputes_resolved_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_disputes")),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_disputes_deal_id_active",
        "disputes",
        ["deal_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(ACTIVE),
    )
    op.create_index(
        "ix_disputes_deal_id_created_at", "disputes", ["deal_id", "created_at"], schema=SCHEMA
    )
    op.create_index(
        "ix_disputes_open_respond_by",
        "disputes",
        ["respond_by"],
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_disputes_opened_by_active",
        "disputes",
        ["opened_by"],
        schema=SCHEMA,
        postgresql_where=sa.text(ACTIVE),
    )
    op.create_index(
        "ix_disputes_respondent_id_active",
        "disputes",
        ["respondent_id"],
        schema=SCHEMA,
        postgresql_where=sa.text(ACTIVE),
    )
    _cancel_reasons(CANCEL_REASONS_NEW)


def downgrade() -> None:
    _cancel_reasons(CANCEL_REASONS_OLD)
    op.drop_table("disputes", schema=SCHEMA)


def _cancel_reasons(values: str) -> None:
    table = f"{SCHEMA}.deals"
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {CANCEL_CHECK}")
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {CANCEL_CHECK}"
        f" CHECK (cancel_reason IN ({values})) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {CANCEL_CHECK}")
