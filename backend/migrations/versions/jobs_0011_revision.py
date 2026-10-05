"""jobs_0011: редакция содержимого заявки — для If-Match правки и решения модератора.

`jobs.version` растёт с любой записью строки: автопроверка публикует заявку, модератор решает,
приходят отклики. Клиент правил с ETag из ответа на прошлую правку и получал ложный 412 (QA
ADV-07), а модератор одобрял редакцию, которой не видел (QA ADV-11). `revision` растёт только
с правкой содержимого клиентом (domain Job.revision): по ней ETag, If-Match и версия кейса
модерации. Заполняется из `version` — ETag, уже выданные клиентам, остаются верными.

Ревизия: jobs_0011 (2026-10-05 20:30:00.000000+00:00)
Предыдущая: platform_0007

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

revision: str = "jobs_0011"
down_revision: str | Sequence[str] | None = "platform_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"


def upgrade() -> None:
    # NOT NULL с константой по умолчанию — без переписывания таблицы (PostgreSQL 11+)
    op.add_column(
        "jobs",
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        schema=SCHEMA,
    )
    op.execute(f"UPDATE {SCHEMA}.jobs SET revision = version")


def downgrade() -> None:
    op.drop_column("jobs", "revision", schema=SCHEMA)
