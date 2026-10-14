"""jobs_0012: место на заявке отклик занимает после проверки (B4, антифрод 2026-10-14).

Раньше отклик занимал одно из `max_responses` мест сразу, ещё на проверке: ночью пять откликов,
ждущих модератора до утра, закрывали заявку для всех. `placed` — отклик прошёл проверку и занял
место; `responses_count` считает только такие. Отклики до этой миграции место уже занимали —
у них `true` (значение по умолчанию заполняет их без переписывания таблицы); новые домен пишет
с `false` до первой пройденной проверки.

Ревизия: jobs_0012 (2026-10-14 10:00:00.000000+00:00)
Предыдущая: notifications_0014

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

revision: str = "jobs_0012"
down_revision: str | Sequence[str] | None = "notifications_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"


def upgrade() -> None:
    # NOT NULL с константой по умолчанию — без переписывания таблицы (PostgreSQL 11+)
    op.add_column(
        "responses",
        sa.Column("placed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("responses", "placed", schema=SCHEMA)
