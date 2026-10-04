"""moderation_0007: цель проверки «работа портфолио» (DEVELOPMENT_PLAN 6.7; ARCHITECTURE §14.1).

Новая работа портфолио ждёт проверки подписи и фото: кейс о ней — объект `portfolio`.
`entity_type` кейсов и `target_type` жалоб (тот же перечень в модели) принимают новое значение.
Длины varchar не меняются (varchar 20 вмещает `portfolio`); CHECK заменяется через NOT VALID и
VALIDATE, как в moderation_0003. Откат возвращает старые списки; кейсы работ откат не удаляет —
VALIDATE тогда упадёт (ADR-0005: данные не теряем).

Ревизия: moderation_0007 (2026-10-04 20:00:00.000000+00:00)
Предыдущая: notifications_0008

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

revision: str = "moderation_0007"
down_revision: str | Sequence[str] | None = "notifications_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "moderation"
BEFORE = (
    "'user', 'profile', 'job', 'response', 'review', 'review_reply', 'message', 'media', 'dispute'"
)
COLUMNS = (("cases", "entity_type"), ("reports", "target_type"))


def upgrade() -> None:
    for table, column in COLUMNS:
        _replace_check(table, column, f"{BEFORE}, 'portfolio'")


def downgrade() -> None:
    for table, column in COLUMNS:
        _replace_check(table, column, BEFORE)


def _replace_check(table: str, column: str, values: str) -> None:
    name = f"ck_{table}_{column}"
    op.drop_constraint(op.f(name), table, type_="check", schema=SCHEMA)
    op.create_check_constraint(
        op.f(name), table, f"{column} IN ({values})", schema=SCHEMA, postgresql_not_valid=True
    )
    op.execute(sa.text(f"ALTER TABLE {SCHEMA}.{table} VALIDATE CONSTRAINT {name}"))
