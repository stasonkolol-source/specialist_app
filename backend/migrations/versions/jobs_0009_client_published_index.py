"""jobs_0009: частичный индекс опубликованных заявок клиента (перф-аудит 2026-10).

«M заявок» в блоке клиента S15 считает заявки клиента, которые когда-либо публиковались
(`client_id = … AND published_at IS NOT NULL`). Индекс ix_jobs_client_id_created_at частичный по
`deleted_at IS NULL` и этот запрос не покрывает — шёл последовательный просмотр jobs.jobs.
Новый индекс строится CONCURRENTLY: таблица живая.

Ревизия: jobs_0009 (2026-10-03 12:00:00.000000+00:00)
Предыдущая: reviews_0003

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

revision: str = "jobs_0009"
down_revision: str | Sequence[str] | None = "reviews_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "jobs"
INDEX = "ix_jobs_client_id_published"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX,
            "jobs",
            ["client_id"],
            schema=SCHEMA,
            postgresql_where=sa.text("published_at IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX, table_name="jobs", schema=SCHEMA, postgresql_concurrently=True, if_exists=True
        )
