"""search_0003: избранное (ARCHITECTURE §7.3 `search.favorites`; DEVELOPMENT_PLAN 4.6).

«Мои мастера» (S12) и — с шагом 5.3 — сохранённые заявки: строка на пару «пользователь — цель».
Не больше 100 записей одного типа (проверка в приложении). Таблица новая и пустая.

Ревизия: search_0003 (2026-10-02 11:25:00.000000+00:00)
Предыдущая: reviews_0001

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

revision: str = "search_0003"
down_revision: str | Sequence[str] | None = "reviews_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "search"


def upgrade() -> None:
    op.create_table(
        "favorites",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("target_type", sa.String(length=15), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "target_type IN ('profile', 'job')", name=op.f("ck_favorites_target_type")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity.users.id"], name=op.f("fk_favorites_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "target_type", "target_id", name=op.f("pk_favorites")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("favorites", schema=SCHEMA)
