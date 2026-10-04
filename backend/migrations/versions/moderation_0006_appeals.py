"""moderation_0006: апелляции (DEVELOPMENT_PLAN 2.5b; ARCHITECTURE §14.4).

Апелляция — кейс очереди Appeals об объекте обжалованного решения (`appeal_of`). Пока она
открыта, по объекту может прийти новый повод (жалоба), и он открывает свой кейс: «один
открытый кейс на объект» (`uq_cases_entity_open`) теперь не считает апелляции. Апелляция на
решение — одна на всю жизнь (`uq_cases_appeal_of`): итог окончательный, повтор — та же.
Индексы — CONCURRENTLY: сначала новый, потом старый снимается, новый получает его имя.
Откат возвращает старый индекс; если апелляция и кейс того же объекта открыты разом, он не
создастся (ADR-0005: данные не теряем).

Ревизия: moderation_0006 (2026-10-04 10:00:00.000000+00:00)
Предыдущая: moderation_0005

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

revision: str = "moderation_0006"
down_revision: str | Sequence[str] | None = "specialists_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "moderation"
OPEN_CASE = "status IN ('pending', 'in_review', 'escalated')"
ENTITY_OPEN = "uq_cases_entity_open"
TEMP = "uq_cases_entity_open_new"
ENTITY = ["entity_type", "entity_id"]


def _swap(where: str) -> None:
    """Индекс «один открытый кейс на объект» с новым предикатом под тем же именем."""
    with op.get_context().autocommit_block():
        op.create_index(
            TEMP,
            "cases",
            ENTITY,
            unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text(where),
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.drop_index(
            ENTITY_OPEN,
            table_name="cases",
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.execute(sa.text(f"ALTER INDEX {SCHEMA}.{TEMP} RENAME TO {ENTITY_OPEN}"))


def upgrade() -> None:
    _swap(f"{OPEN_CASE} AND appeal_of IS NULL")
    with op.get_context().autocommit_block():
        op.create_index(
            "uq_cases_appeal_of",
            "cases",
            ["appeal_of"],
            unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text("appeal_of IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "uq_cases_appeal_of",
            table_name="cases",
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_exists=True,
        )
    _swap(OPEN_CASE)
