"""specialists_0004: редакция профиля и подписи работы портфолио — версия для модерации.

Модератор одобрял редакцию, которой не видел (QA ADV-11): исполнитель правил профиль или
подпись после карточки кейса, и «Одобрить» публиковало правку. `revision` растёт только с
правкой исполнителя (domain Profile.revision, PortfolioItem.revision); кейс помнит, какую
редакцию показал, и решение действует только на неё. `profiles.version` не годится: её меняют и
«доступен сегодня», пауза, отметки системы. Колонки NOT NULL с константой — без переписывания
таблиц; прежние кейсы версию не помнят, и им редакция не нужна.

Ревизия: specialists_0004 (2026-10-05 20:31:00.000000+00:00)
Предыдущая: jobs_0011

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

revision: str = "specialists_0004"
down_revision: str | Sequence[str] | None = "jobs_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "specialists"
TABLES = ("profiles", "portfolio_items")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
            schema=SCHEMA,
        )


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "revision", schema=SCHEMA)
