"""reviews_0001: агрегаты рейтинга профилей (ARCHITECTURE §7.3; DEVELOPMENT_PLAN 4.6).

`reviews.rating_aggregates` — по строке на профиль с отзывами по сделкам: число, среднее,
байесовское среднее и нижняя граница для ранжирования, гистограмма звёзд (S11) и средние по
критериям. Пересчитывают её отзывы (7.2); до того таблица пуста. Новая и пустая — блокировок нет.

Ревизия: reviews_0001 (2026-10-02 11:20:00.000000+00:00)
Предыдущая: search_0002

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

revision: str = "reviews_0001"
down_revision: str | Sequence[str] | None = "search_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "reviews"


def upgrade() -> None:
    op.create_table(
        "rating_aggregates",
        sa.Column("subject_profile_id", sa.Uuid(), nullable=False),
        sa.Column("rating_count", sa.Integer(), nullable=False),
        sa.Column("rating_avg", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("rating_bayes", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("rating_lower_bound", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column(
            "distribution",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{0,0,0,0,0}'"),
            nullable=False,
        ),
        sa.Column(
            "criteria_avg",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rating_count >= 0", name=op.f("ck_rating_aggregates_rating_count_non_negative")
        ),
        sa.CheckConstraint(
            "cardinality(distribution) = 5",
            name=op.f("ck_rating_aggregates_distribution_five_stars"),
        ),
        sa.ForeignKeyConstraint(
            ["subject_profile_id"],
            ["specialists.profiles.id"],
            name=op.f("fk_rating_aggregates_subject_profile_id_profiles"),
        ),
        sa.PrimaryKeyConstraint("subject_profile_id", name=op.f("pk_rating_aggregates")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("rating_aggregates", schema=SCHEMA)
