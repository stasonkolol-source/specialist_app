"""specialists_0003: когда специалисту напоминали о давно не обновлённом профиле (DEVELOPMENT_PLAN 5.7).

`profile.stale_reminder` — не чаще раза в 2 недели (ARCHITECTURE §11.3, §12.3): отметка
`stale_reminded_at` пишется отдельным UPDATE, не трогая `updated_at` — по нему и решается, давно
ли профиль не обновлялся. Колонка nullable — без переписывания таблицы.

Ревизия: specialists_0003 (2026-10-03 21:10:00.000000+00:00)
Предыдущая: notifications_0006

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

revision: str = "specialists_0003"
down_revision: str | Sequence[str] | None = "notifications_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "specialists"


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("stale_reminded_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("profiles", "stale_reminded_at", schema=SCHEMA)
