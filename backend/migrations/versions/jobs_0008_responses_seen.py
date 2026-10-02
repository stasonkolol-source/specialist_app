"""jobs_0008: когда клиент последний раз смотрел отклики (S22, S23; DEVELOPMENT_PLAN 5.6).

`jobs.jobs.responses_seen_at` — клиент открыл отклики на S23: отклики, прошедшие проверку после
этой отметки, — «новые» (бейдж S22, уведомление `response.received`). Отметка не меняет версию
заявки: просмотр откликов не ломает правку с If-Match. Колонка nullable без значения по
умолчанию — добавление не переписывает таблицу.

Ревизия: jobs_0008 (2026-10-02 23:30:00.000000+00:00)
Предыдущая: jobs_0007

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

revision: str = "jobs_0008"
down_revision: str | Sequence[str] | None = "jobs_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("responses_seen_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("jobs", "responses_seen_at", schema=SCHEMA)
