"""jobs_0003: лента заявок (ARCHITECTURE §9.6; DEVELOPMENT_PLAN 5.3).

`jobs.hidden_jobs` — «не интересно» (S15): заявка скрыта из ленты исполнителя; первичный ключ
(user_id, job_id) обслуживает и исключение в ленте. Индексы ленты на опубликованных: GiST по
смещённой точке — радиус от точки зрителя, GIN по `category_path` — «категория с
подкатегориями». Таблица `jobs` живая — индексы строятся CONCURRENTLY.

Ревизия: jobs_0003 (2026-10-02 17:00:00.000000+00:00)
Предыдущая: jobs_0002

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

revision: str = "jobs_0003"
down_revision: str | Sequence[str] | None = "jobs_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"
PUBLISHED = sa.text("status = 'published'")


def upgrade() -> None:
    op.create_table(
        "hidden_jobs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity.users.id"], name=op.f("fk_hidden_jobs_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.jobs.id"], name=op.f("fk_hidden_jobs_job_id_jobs")
        ),
        sa.PrimaryKeyConstraint("user_id", "job_id", name=op.f("pk_hidden_jobs")),
        schema=SCHEMA,
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_jobs_point_public",
            "jobs",
            ["point_public"],
            schema=SCHEMA,
            postgresql_using="gist",
            postgresql_where=PUBLISHED,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_jobs_category_path",
            "jobs",
            ["category_path"],
            schema=SCHEMA,
            postgresql_using="gin",
            postgresql_where=PUBLISHED,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name in ("ix_jobs_category_path", "ix_jobs_point_public"):
            op.drop_index(
                name,
                table_name="jobs",
                schema=SCHEMA,
                postgresql_concurrently=True,
                if_exists=True,
            )
    op.drop_table("hidden_jobs", schema=SCHEMA)
