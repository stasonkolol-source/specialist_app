"""jobs_0005: отклики (ARCHITECTURE §7.9; DEVELOPMENT_PLAN 5.4).

`jobs.responses` — подагрегат заявки: строки пишет репозиторий заявки под блокировкой её строки,
поэтому лимит мест (`jobs.max_responses`) не обходится параллельными откликами. Один отклик на
заявку от исполнителя — частичный уникальный индекс по неудалённым. `review` — проверка текста
модерацией (клиент видит только `clear`), `revision` — редакция, которую проверяли. Индексы — для
списка откликов заявки (S23) и откликов исполнителя (S17). Таблица новая — индексы строятся
сразу.

Ревизия: jobs_0005 (2026-10-02 20:00:00.000000+00:00)
Предыдущая: jobs_0004

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

revision: str = "jobs_0005"
down_revision: str | Sequence[str] | None = "jobs_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"


def upgrade() -> None:
    op.create_table(
        "responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("performer_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="submitted", nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("price_type", sa.String(length=18), nullable=False),
        sa.Column("price_amount", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default=sa.text("'RSD'"), nullable=False),
        sa.Column("availability_note", sa.Text(), nullable=True),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("review", sa.String(length=15), server_default="pending", nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('submitted', 'viewed', 'shortlisted', 'accepted', 'declined',"
            " 'withdrawn', 'not_selected')",
            name=op.f("ck_responses_status"),
        ),
        sa.CheckConstraint(
            "price_type IN ('fixed', 'from', 'hourly', 'negotiable')",
            name=op.f("ck_responses_price_type"),
        ),
        sa.CheckConstraint(
            "review IN ('pending', 'clear', 'blocked')", name=op.f("ck_responses_review")
        ),
        sa.CheckConstraint(
            "char_length(message) BETWEEN 1 AND 1500", name=op.f("ck_responses_message_length")
        ),
        sa.CheckConstraint(
            "char_length(availability_note) <= 200",
            name=op.f("ck_responses_availability_note_length"),
        ),
        sa.CheckConstraint(
            "(price_type = 'negotiable') = (price_amount IS NULL)",
            name=op.f("ck_responses_price_amount_set"),
        ),
        sa.CheckConstraint("currency = 'RSD'", name=op.f("ck_responses_currency_rsd")),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.jobs.id"], name=op.f("fk_responses_job_id_jobs")
        ),
        sa.ForeignKeyConstraint(
            ["performer_id"], ["identity.users.id"], name=op.f("fk_responses_performer_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["specialists.profiles.id"],
            name=op.f("fk_responses_profile_id_profiles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_responses")),
        schema=SCHEMA,
    )
    op.create_index(
        "uq_responses_job_id_performer_id",
        "responses",
        ["job_id", "performer_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_responses_job_id_created_at", "responses", ["job_id", "created_at"], schema=SCHEMA
    )
    op.create_index(
        "ix_responses_performer_id_created_at",
        "responses",
        ["performer_id", sa.text("created_at DESC")],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("responses", schema=SCHEMA)
