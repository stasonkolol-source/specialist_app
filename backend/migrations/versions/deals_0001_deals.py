"""deals_0001: сделки и история их статусов (ARCHITECTURE §7.3, §7.9; DEVELOPMENT_PLAN 6.1a).

`deals.deals` — договорённость клиента и исполнителя: из отклика (`job_response`), из чата
(`chat`, 6.4) или без заявки (`direct`). Ссылки вверх по DAG (`job_id`, `response_id`,
`conversation_id`) — без FK; один отклик — одна сделка (`uq_deals_response_id`). Цена — только
RSD, деньги мимо платформы (ADR-0017). `deals.status_history` — переходы статусов (§7.10),
создание — без `from_status`. Споры — 6.1c. Таблицы новые и пустые — блокировок нет.

Ревизия: deals_0001 (2026-10-02 19:00:00.000000+00:00)
Предыдущая: growth_0003

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

revision: str = "deals_0001"
down_revision: str | Sequence[str] | None = "growth_0003"
branch_labels: str | Sequence[str] | None = ("deals",)
depends_on: str | Sequence[str] | None = None

SCHEMA = "deals"


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("performer_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=True),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("response_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("title_snapshot", sa.Text(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=17), server_default="agreed", nullable=False),
        sa.Column("proposed_by", sa.Uuid(), nullable=True),
        sa.Column("price_type", sa.String(length=18), nullable=True),
        sa.Column("agreed_price", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'RSD'"), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("client_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("performer_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancel_reason", sa.String(length=23), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "origin IN ('job_response', 'direct', 'chat')", name=op.f("ck_deals_origin")
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'agreed', 'completed', 'cancelled', 'disputed')",
            name=op.f("ck_deals_status"),
        ),
        sa.CheckConstraint(
            "price_type IN ('fixed', 'from', 'hourly', 'negotiable')",
            name=op.f("ck_deals_price_type"),
        ),
        sa.CheckConstraint(
            "cancel_reason IN ('plans_changed', 'no_agreement', 'no_contact', 'other', 'expired',"
            " 'account_deleted')",
            name=op.f("ck_deals_cancel_reason"),
        ),
        sa.CheckConstraint(
            "char_length(title_snapshot) BETWEEN 1 AND 120", name=op.f("ck_deals_title_length")
        ),
        sa.CheckConstraint("client_id <> performer_id", name=op.f("ck_deals_two_parties")),
        sa.CheckConstraint(
            "origin <> 'job_response' OR (job_id IS NOT NULL AND response_id IS NOT NULL)",
            name=op.f("ck_deals_response_origin_refs"),
        ),
        sa.CheckConstraint("currency = 'RSD'", name=op.f("ck_deals_currency_rsd")),
        sa.ForeignKeyConstraint(
            ["client_id"], ["identity.users.id"], name=op.f("fk_deals_client_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["performer_id"], ["identity.users.id"], name=op.f("fk_deals_performer_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["specialists.profiles.id"], name=op.f("fk_deals_profile_id_profiles")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["catalog.categories.id"],
            name=op.f("fk_deals_category_id_categories"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deals")),
        sa.UniqueConstraint("response_id", name=op.f("uq_deals_response_id")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_deals_client_id_created_at", "deals", ["client_id", "created_at"], schema=SCHEMA
    )
    op.create_index(
        "ix_deals_performer_id_created_at", "deals", ["performer_id", "created_at"], schema=SCHEMA
    )
    op.create_index(
        "ix_deals_job_id",
        "deals",
        ["job_id"],
        schema=SCHEMA,
        postgresql_where=sa.text("job_id IS NOT NULL"),
    )
    op.create_table(
        "status_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_kind", sa.String(length=17), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'moderator', 'system')", name=op.f("ck_status_history_actor_kind")
        ),
        sa.ForeignKeyConstraint(
            ["deal_id"], ["deals.deals.id"], name=op.f("fk_status_history_deal_id_deals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_status_history")),
        schema=SCHEMA,
    )
    op.create_index("ix_status_history_deal_id", "status_history", ["deal_id"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("status_history", schema=SCHEMA)
    op.drop_table("deals", schema=SCHEMA)
