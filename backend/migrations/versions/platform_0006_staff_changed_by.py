"""platform_0006: кто из персонала последним менял флаг и конфигурацию клиентов.

Шаг 2.7b (вторая часть): разделы «Feature flags» и «Client-config» в админке показывают, кто и
когда менял строку. `updated_by` — id сотрудника (identity.users), без внешнего ключа: строка
конфигурации не должна мешать удалению аккаунта, а полная история — в platform.audit_log. NULL —
значение из миграции или SQL. Колонки новые и nullable — без перезаписи таблиц.

Ревизия: platform_0006 (2026-10-04 15:00:00.000000+00:00)
Предыдущая: reviews_0004

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

revision: str = "platform_0006"
down_revision: str | Sequence[str] | None = "reviews_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "platform"
TABLES = ("feature_flags", "client_config")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("updated_by", sa.Uuid(), nullable=True), schema=SCHEMA)


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "updated_by", schema=SCHEMA)
