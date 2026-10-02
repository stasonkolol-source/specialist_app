"""search_0002: журнал запросов без результатов (ARCHITECTURE §9.2; DEVELOPMENT_PLAN 4.2).

Запрос выдачи, который ничего не нашёл, пишется в `search.query_log`: из него пополняется
словарь категорий. Пользователя нет — для словаря важен текст. `q_norm` — тот же ключ
`platform.search_norm`, что у словаря: группировка «электрик» и «elektricar» вместе.
Таблица новая и пустая.

Ревизия: search_0002 (2026-10-02 10:40:00.000000+00:00)
Предыдущая: search_0001

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

revision: str = "search_0002"
down_revision: str | Sequence[str] | None = "search_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "search"


def upgrade() -> None:
    op.create_table(
        "query_log",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("q", sa.String(length=100), nullable=False),
        sa.Column(
            "q_norm",
            sa.Text(),
            sa.Computed("platform.search_norm(q::text)", persisted=True),
            nullable=False,
        ),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column(
            "filters",
            postgresql.ARRAY(sa.String(length=32)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("did_you_mean", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_query_log")),
        schema=SCHEMA,
    )
    op.create_index("ix_query_log_created_at", "query_log", ["created_at"], schema=SCHEMA)
    op.create_index("ix_query_log_q_norm", "query_log", ["q_norm"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("query_log", schema=SCHEMA)
