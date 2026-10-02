"""jobs_0004: сохранённые заявки (сердечко S15, сегмент «Задачи» S12; DEVELOPMENT_PLAN 5.3).

`jobs.saved_jobs` — пара «исполнитель — заявка», как `hidden_jobs`: заявка и её видимость — у
модуля jobs, поэтому сохранённые заявки живут здесь, а не в `search.favorites`. Первичный ключ
(user_id, job_id) обслуживает и список пользователя — в нём не больше ста строк.

Ревизия: jobs_0004 (2026-10-02 18:30:00.000000+00:00)
Предыдущая: jobs_0003

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

revision: str = "jobs_0004"
down_revision: str | Sequence[str] | None = "jobs_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"


def upgrade() -> None:
    op.create_table(
        "saved_jobs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity.users.id"], name=op.f("fk_saved_jobs_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.jobs.id"], name=op.f("fk_saved_jobs_job_id_jobs")
        ),
        sa.PrimaryKeyConstraint("user_id", "job_id", name=op.f("pk_saved_jobs")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("saved_jobs", schema=SCHEMA)
