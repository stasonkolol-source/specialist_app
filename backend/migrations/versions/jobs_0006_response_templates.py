"""jobs_0006: шаблоны откликов (S57; DEVELOPMENT_PLAN 5.5).

`jobs.response_templates` — готовое сообщение, цена и «когда смогу» исполнителя: не больше двух
(сериализация — advisory lock пользователя в транзакции), `position` 0 — основной. Таблица новая
— индекс строится сразу.

Ревизия: jobs_0006 (2026-10-02 21:30:00.000000+00:00)
Предыдущая: jobs_0005

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

revision: str = "jobs_0006"
down_revision: str | Sequence[str] | None = "jobs_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"


def upgrade() -> None:
    op.create_table(
        "response_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("price_type", sa.String(length=18), nullable=False),
        sa.Column("price_amount", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'RSD'"), nullable=False),
        sa.Column("availability_note", sa.Text(), nullable=True),
        sa.Column("position", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "price_type IN ('fixed', 'from', 'hourly', 'negotiable')",
            name=op.f("ck_response_templates_price_type"),
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 40", name=op.f("ck_response_templates_title_length")
        ),
        sa.CheckConstraint(
            "char_length(message) BETWEEN 1 AND 1500",
            name=op.f("ck_response_templates_message_length"),
        ),
        sa.CheckConstraint(
            "char_length(availability_note) <= 200",
            name=op.f("ck_response_templates_availability_note_length"),
        ),
        sa.CheckConstraint(
            "(price_type = 'negotiable') = (price_amount IS NULL)",
            name=op.f("ck_response_templates_price_amount_set"),
        ),
        sa.CheckConstraint("currency = 'RSD'", name=op.f("ck_response_templates_currency_rsd")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity.users.id"], name=op.f("fk_response_templates_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_response_templates")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_response_templates_user_id_position",
        "response_templates",
        ["user_id", "position"],
        schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("response_templates", schema=SCHEMA)
