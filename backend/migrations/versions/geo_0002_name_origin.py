"""geo_0002: кто ведёт название записи справочника — сид или админка.

Шаг 2.7b (вторая часть): названия правятся в админке формой LocalizedText (ru, sr-Cyrl, sr-Latn,
en). Правка ставит `name_origin = 'admin'`, и следующий `cli seed` такое название не
переписывает — как `origin = admin` у контент-правил (moderation_0001); остальные поля строки
по-прежнему ведёт сид. По умолчанию — 'seed': существующие строки пришли из сидов. Справочник —
десятки и сотни строк: колонка с константой по умолчанию и CHECK добавляются без долгой блокировки.

Ревизия: geo_0002 (2026-10-04 15:02:00.000000+00:00)
Предыдущая: catalog_0002

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

revision: str = "geo_0002"
down_revision: str | Sequence[str] | None = "catalog_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "geo"
TABLES = ("cities", "districts")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("name_origin", sa.String(length=13), server_default="seed", nullable=False),
            schema=SCHEMA,
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_name_origin"),
            table,
            "name_origin IN ('seed', 'admin')",
            schema=SCHEMA,
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_constraint(op.f(f"ck_{table}_name_origin"), table, type_="check", schema=SCHEMA)
        op.drop_column(table, "name_origin", schema=SCHEMA)
