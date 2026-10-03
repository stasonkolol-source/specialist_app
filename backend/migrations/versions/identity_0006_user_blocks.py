"""identity_0006: блокировки между пользователями (DEVELOPMENT_PLAN 4.7; ARCHITECTURE §7.3).

`identity.user_blocks` — «кто кого заблокировал» (App Store 1.2): ключ — пара, повтор ничего не
добавляет; обратный индекс по `blocked_id` — «кто заблокировал меня» для фильтров выдачи, ленты и
приглашений. Себя не блокируют (CHECK). Таблица новая и пустая — блокировок нет.

Ревизия: identity_0006 (2026-10-03 18:00:00.000000+00:00)
Предыдущая: notifications_0005

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

revision: str = "identity_0006"
down_revision: str | Sequence[str] | None = "notifications_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"


def upgrade() -> None:
    op.create_table(
        "user_blocks",
        sa.Column("blocker_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("blocker_id <> blocked_id", name=op.f("ck_user_blocks_not_self")),
        sa.ForeignKeyConstraint(
            ["blocker_id"], ["identity.users.id"], name=op.f("fk_user_blocks_blocker_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["blocked_id"], ["identity.users.id"], name=op.f("fk_user_blocks_blocked_id_users")
        ),
        sa.PrimaryKeyConstraint("blocker_id", "blocked_id", name=op.f("pk_user_blocks")),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_user_blocks_blocked_id"), "user_blocks", ["blocked_id"], unique=False, schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_blocks_blocked_id"), table_name="user_blocks", schema=SCHEMA)
    op.drop_table("user_blocks", schema=SCHEMA)
