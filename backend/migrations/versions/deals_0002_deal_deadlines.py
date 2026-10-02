"""deals_0002: напоминание и вопрос «Работа выполнена?» — отметки и индексы сроков (6.1b).

`reminded_at` — сторонам напомнили о времени сделки (за 2 ч), `completion_prompted_at` — задали
вопрос «Работа выполнена?» (через 3 ч после времени, без времени — через сутки после
договорённости): каждое — один раз. Частичные индексы — для проходов периодических задач:
идущие сделки по времени и по моменту договорённости, предложения «Договорились» по возрасту
(истекают через 72 ч). Колонки nullable, индексы — CONCURRENTLY.

Ревизия: deals_0002 (2026-10-02 20:00:00.000000+00:00)
Предыдущая: identity_0005

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

revision: str = "deals_0002"
down_revision: str | Sequence[str] | None = "identity_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "deals"
INDEXES = (
    ("ix_deals_agreed_scheduled_at", ["scheduled_at"], "status = 'agreed'"),
    ("ix_deals_agreed_agreed_at", ["agreed_at"], "status = 'agreed'"),
    ("ix_deals_proposed_created_at", ["created_at"], "status = 'proposed'"),
)


def upgrade() -> None:
    op.add_column(
        "deals", sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "deals",
        sa.Column("completion_prompted_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    with op.get_context().autocommit_block():
        for name, columns, where in INDEXES:
            op.create_index(
                name,
                "deals",
                columns,
                unique=False,
                schema=SCHEMA,
                postgresql_where=sa.text(where),
                postgresql_concurrently=True,
                if_not_exists=True,
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _, _ in INDEXES:
            op.drop_index(
                name,
                table_name="deals",
                schema=SCHEMA,
                postgresql_concurrently=True,
                if_exists=True,
            )
    op.drop_column("deals", "completion_prompted_at", schema=SCHEMA)
    op.drop_column("deals", "reminded_at", schema=SCHEMA)
