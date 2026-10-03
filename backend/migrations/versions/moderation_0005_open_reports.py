"""moderation_0005: одна открытая жалоба человека на объект (DEVELOPMENT_PLAN 4.7; ARCHITECTURE §7.3).

Приём жалоб (`POST /reports`): повтор того же человека на тот же объект, пока кейс не решён, —
та же жалоба; после решения новая жалоба — снова повод. Уникальность по паре «кто — что» на
всю жизнь (moderation_0002) заменяется частичным уникальным индексом `WHERE status = 'open'`:
сначала индекс (CONCURRENTLY), потом снимается старое ограничение. Индекс по `case_id` — решение
по кейсу закрывает его жалобы. Откат возвращает ограничение; если после решения кто-то
пожаловался снова, оно не создастся (ADR-0005: данные не теряем).

Ревизия: moderation_0005 (2026-10-03 18:05:00.000000+00:00)
Предыдущая: identity_0006

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

revision: str = "moderation_0005"
down_revision: str | Sequence[str] | None = "identity_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "moderation"
OLD = "uq_reports_reporter_id_target_type_target_id"
TARGET = ["reporter_id", "target_type", "target_id"]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "uq_reports_open",
            "reports",
            TARGET,
            unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text("status = 'open'"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_reports_case_id",
            "reports",
            ["case_id"],
            unique=False,
            schema=SCHEMA,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
    op.drop_constraint(op.f(OLD), "reports", type_="unique", schema=SCHEMA)


def downgrade() -> None:
    op.create_unique_constraint(op.f(OLD), "reports", TARGET, schema=SCHEMA)
    with op.get_context().autocommit_block():
        for name in ("ix_reports_case_id", "uq_reports_open"):
            op.drop_index(
                name,
                table_name="reports",
                schema=SCHEMA,
                postgresql_concurrently=True,
                if_exists=True,
            )
