"""jobs_0002: напоминание о конце срока заявки (ARCHITECTURE §11.3 `job.expiring`; план 5.1).

`jobs.jobs.expiry_reminded_at` — когда клиенту напомнили, что опубликованная заявка закроется
через два часа: одно напоминание за срок, продление и новая публикация его сбрасывают. Колонка
nullable без значения по умолчанию — добавление не переписывает таблицу.

Ревизия: jobs_0002 (2026-10-02 15:00:00.000000+00:00)
Предыдущая: jobs_0001

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

revision: str = "jobs_0002"
down_revision: str | Sequence[str] | None = "jobs_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("expiry_reminded_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("jobs", "expiry_reminded_at", schema=SCHEMA)
