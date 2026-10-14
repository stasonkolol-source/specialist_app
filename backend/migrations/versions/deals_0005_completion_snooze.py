"""deals_0005: «Ещё нет» под «Работа выполнена?» — перенос вопроса на сутки (не больше трёх раз).

`completion_snoozes` — сколько раз вопрос уже переносили (счётчик в сделке, лимит — в домене),
`completion_snoozed_until` — когда спросить снова: после переноса срок вопроса — он, а не время
работы. Частичный индекс — для прохода `deals.completion_prompts` по перенесённым сделкам, как
индексы сроков deals_0002. Колонка со значением по умолчанию — без переписывания таблицы
(PostgreSQL 11+), индекс — CONCURRENTLY.

Ревизия: deals_0005 (2026-10-14 12:00:00.000000+00:00)
Предыдущая: notifications_0013

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

revision: str = "deals_0005"
down_revision: str | Sequence[str] | None = "notifications_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "deals"
INDEX = "ix_deals_agreed_completion_snoozed_until"


def upgrade() -> None:
    op.add_column(
        "deals",
        sa.Column(
            "completion_snoozes", sa.SmallInteger(), server_default=sa.text("0"), nullable=False
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "deals",
        sa.Column("completion_snoozed_until", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    with op.get_context().autocommit_block():
        op.create_index(
            INDEX,
            "deals",
            ["completion_snoozed_until"],
            unique=False,
            schema=SCHEMA,
            postgresql_where=sa.text("status = 'agreed'"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX,
            table_name="deals",
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.drop_column("deals", "completion_snoozed_until", schema=SCHEMA)
    op.drop_column("deals", "completion_snoozes", schema=SCHEMA)
