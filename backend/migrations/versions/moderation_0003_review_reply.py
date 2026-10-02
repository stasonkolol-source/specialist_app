"""moderation_0003: цель проверки «ответ на отзыв» (DEVELOPMENT_PLAN 7.2; ARCHITECTURE §14.1).

Ответ исполнителя на отзыв проверяется отдельно от самого отзыва: нарушение в ответе скрывает
ответ, а не отзыв клиента. `entity_type` кейсов и `target_type` жалоб принимают `review_reply`:
колонки шире (varchar 16 → 20 — только каталог, таблица не переписывается), CHECK заменяется
через NOT VALID и VALIDATE (проверка строк без эксклюзивной блокировки).

Ревизия: moderation_0003 (2026-10-03 00:55:00.000000+00:00)
Предыдущая: reviews_0002

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

revision: str = "moderation_0003"
down_revision: str | Sequence[str] | None = "reviews_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "moderation"
BEFORE = "'user', 'profile', 'job', 'response', 'review', 'message', 'media'"
AFTER = "'user', 'profile', 'job', 'response', 'review', 'review_reply', 'message', 'media'"
COLUMNS = (("cases", "entity_type"), ("reports", "target_type"))


def upgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.String(length=20),
            existing_type=sa.String(length=16),
            existing_nullable=False,
            schema=SCHEMA,
        )
        _replace_check(table, column, AFTER)


def downgrade() -> None:
    for table, column in COLUMNS:
        _replace_check(table, column, BEFORE)
        op.alter_column(
            table,
            column,
            type_=sa.String(length=16),
            existing_type=sa.String(length=20),
            existing_nullable=False,
            schema=SCHEMA,
        )


def _replace_check(table: str, column: str, values: str) -> None:
    name = f"ck_{table}_{column}"
    op.drop_constraint(op.f(name), table, type_="check", schema=SCHEMA)
    op.create_check_constraint(
        op.f(name), table, f"{column} IN ({values})", schema=SCHEMA, postgresql_not_valid=True
    )
    op.execute(sa.text(f"ALTER TABLE {SCHEMA}.{table} VALIDATE CONSTRAINT {name}"))
