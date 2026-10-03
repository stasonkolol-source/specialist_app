"""moderation_0004: кейс спора по сделке (DEVELOPMENT_PLAN 6.1c; ARCHITECTURE §14.4).

Спор (`deals.disputes`) — кейс объекта `dispute` с поводом `dispute`: `entity_type` кейсов (и
`target_type` жалоб — тот же перечень в модели) и `trigger` кейсов принимают новое значение.
Длины varchar не меняются; CHECK заменяется через NOT VALID и VALIDATE, как в moderation_0003.
Откат возвращает старые списки; кейсы споров откат не удаляет — VALIDATE тогда упадёт
(ADR-0005: данные не теряем).

Ревизия: moderation_0004 (2026-10-03 12:10:00.000000+00:00)
Предыдущая: media_0005

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

revision: str = "moderation_0004"
down_revision: str | Sequence[str] | None = "media_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "moderation"
ENTITIES = "'user', 'profile', 'job', 'response', 'review', 'review_reply', 'message', 'media'"
TRIGGERS = "'new_content', 'edit', 'report', 'auto_flag', 'appeal'"
CHECKS = (
    ("cases", "entity_type", ENTITIES),
    ("reports", "target_type", ENTITIES),
    ("cases", "trigger", TRIGGERS),
)


def upgrade() -> None:
    for table, column, values in CHECKS:
        _replace_check(table, column, f"{values}, 'dispute'")


def downgrade() -> None:
    for table, column, values in CHECKS:
        _replace_check(table, column, values)


def _replace_check(table: str, column: str, values: str) -> None:
    name = f"ck_{table}_{column}"
    op.drop_constraint(op.f(name), table, type_="check", schema=SCHEMA)
    op.create_check_constraint(
        op.f(name), table, f"{column} IN ({values})", schema=SCHEMA, postgresql_not_valid=True
    )
    op.execute(sa.text(f"ALTER TABLE {SCHEMA}.{table} VALIDATE CONSTRAINT {name}"))
