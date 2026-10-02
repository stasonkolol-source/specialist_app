"""identity_0005: факты завершённых сделок — уровень доверия 2 (ADR-0016 §2, DEVELOPMENT_PLAN 6.1a).

`identity.completed_deals` — по строке на сторону завершённой сделки: пишет подписчик
DealCompleted, ключ (пользователь, сделка) не даёт повтору задачи удвоить факт. Сделка — модуль
выше по DAG: `deal_id` без FK. Таблица новая и пустая — блокировок нет.

Ревизия: identity_0005 (2026-10-02 19:30:00.000000+00:00)
Предыдущая: deals_0001

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

revision: str = "identity_0005"
down_revision: str | Sequence[str] | None = "deals_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "identity"


def upgrade() -> None:
    op.create_table(
        "completed_deals",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("deal_id", sa.Uuid(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["identity.users.id"], name=op.f("fk_completed_deals_user_id_users")
        ),
        sa.PrimaryKeyConstraint("user_id", "deal_id", name=op.f("pk_completed_deals")),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("completed_deals", schema=SCHEMA)
