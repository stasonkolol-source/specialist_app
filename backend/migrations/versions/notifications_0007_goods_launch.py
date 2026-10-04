"""notifications_0007: группа `goods_launch` — «Сообщить о запуске» раздела «Вещи» (7.5).

Кнопка на S58 включает группу, переключатель S43 выключает: выбор хранится в `preferences`, как
у остальных групп; модуля goods и его таблиц нет (ADR-0019). Новый CHECK — надмножество
старого. Имя группы длиннее прежних: varchar(19) → varchar(20), как считает `str_enum`
(длина + 8). Увеличение длины varchar — только каталог, таблица не переписывается. CHECK — DROP
→ ADD … NOT VALID → VALIDATE после commit, как в notifications_0005. Downgrade удаляет выбор
новой группы.

Ревизия: notifications_0007 (2026-10-04 10:00:00.000000+00:00)
Предыдущая: specialists_0003

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "notifications_0007"
down_revision: str | Sequence[str] | None = "growth_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "notifications.preferences"
CHECK = "ck_preferences_event_group"
OLD = "'job_matches', 'responses', 'messages', 'deals', 'marketing', 'account'"
NEW = "'job_matches', 'responses', 'messages', 'deals', 'marketing', 'goods_launch', 'account'"


def _groups(values: str) -> None:
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CHECK}")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK} CHECK (event_group IN ({values})) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CHECK}")


def upgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN event_group TYPE varchar(20)")
    _groups(NEW)


def downgrade() -> None:
    op.execute(f"DELETE FROM {TABLE} WHERE event_group = 'goods_launch'")
    _groups(OLD)
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN event_group TYPE varchar(19)")
