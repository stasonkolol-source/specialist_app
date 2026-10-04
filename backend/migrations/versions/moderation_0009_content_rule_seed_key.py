"""moderation_0009: строка контент-правила помнит своё правило сида (2.7b, ревью безопасности).

`cli seed` узнавал строку сида по паре (kind, pattern): правило, чей шаблон поправили в админке,
под пару больше не подходило, и импорт вставлял исходное правило заново — включённым, с
`origin = seed`. `content_rules.seed_key` — `<kind>:<pattern>` правила сида, как оно записано в
файле; правка в админке его не меняет, импорт ищет строку по нему. Строкам сида ключ ставит эта
миграция (таблица — сотни строк); строки админки остаются с NULL. Уникальный индекс — CONCURRENTLY.

Ревизия: moderation_0009 (2026-10-04 20:00:00.000000+00:00)
Предыдущая: identity_0009

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

revision: str = "moderation_0009"
down_revision: str | Sequence[str] | None = "identity_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "moderation"
INDEX = "uq_content_rules_seed_key"


def upgrade() -> None:
    op.add_column(
        "content_rules", sa.Column("seed_key", sa.String(length=216), nullable=True), schema=SCHEMA
    )
    op.execute(
        "UPDATE moderation.content_rules SET seed_key = kind || ':' || pattern"
        " WHERE origin = 'seed'"
    )
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX,
            "content_rules",
            ["seed_key"],
            unique=True,
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX,
            table_name="content_rules",
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.drop_column("content_rules", "seed_key", schema=SCHEMA)
