"""search_0004: время ответа специалиста в read-model (DEVELOPMENT_PLAN 6.3b).

`search.specialist_index.response_time_minutes` — медиана первого ответа в диалогах за 30 дней
(«Обычно отвечает за …» на S08), её раз в час пишет `search.response_time_stats`; NULL — диалогов
с ответом меньше пяти. Колонка nullable без значения по умолчанию — изменение только каталога,
таблица не переписывается.

Ревизия: search_0004 (2026-10-02 23:40:00.000000+00:00)
Предыдущая: messaging_0002

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

revision: str = "search_0004"
down_revision: str | Sequence[str] | None = "messaging_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "search"


def upgrade() -> None:
    op.add_column(
        "specialist_index",
        sa.Column("response_time_minutes", sa.Integer(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("specialist_index", "response_time_minutes", schema=SCHEMA)
