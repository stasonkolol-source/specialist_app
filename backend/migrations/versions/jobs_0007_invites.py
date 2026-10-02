"""jobs_0007: приглашения в заявку и прямой запрос (S21, S23, S08; DEVELOPMENT_PLAN 5.6).

`jobs.invites` — профиль специалиста, приглашённый в опубликованную заявку или получивший прямой
запрос (заявка с `visibility = direct`). `performer_id` — владелец профиля: по нему проверяется,
видна ли прямая заявка исполнителю, и строится «Меня пригласили». Таблица новая — индекс строится
сразу.

Ревизия: jobs_0007 (2026-10-02 22:30:00.000000+00:00)
Предыдущая: jobs_0006

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

revision: str = "jobs_0007"
down_revision: str | Sequence[str] | None = "jobs_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"


def upgrade() -> None:
    op.create_table(
        "invites",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("performer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "invited_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.jobs.id"], name=op.f("fk_invites_job_id_jobs")),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["specialists.profiles.id"],
            name=op.f("fk_invites_profile_id_profiles"),
        ),
        sa.ForeignKeyConstraint(
            ["performer_id"], ["identity.users.id"], name=op.f("fk_invites_performer_id_users")
        ),
        sa.PrimaryKeyConstraint("job_id", "profile_id", name=op.f("pk_invites")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_invites_performer_id_job_id", "invites", ["performer_id", "job_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_table("invites", schema=SCHEMA)
