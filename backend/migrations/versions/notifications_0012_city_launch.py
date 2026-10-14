"""notifications_0012: группа `city_launch` — лист ожидания города «скоро» (S02a).

«Сообщить о запуске» на S02a включает группу, переключатель S43 выключает: выбор хранится в
`preferences`, как у `goods_launch` (notifications_0007), своей таблицы нет. Рассылка о запуске
города — из админки этой группе: новое значение и в `broadcasts` (ограничение по значениям
группы и «только opt-in»). Длина varchar не меняется: имя короче `goods_launch`.

Списки CHECK не переписываются целиком, а берутся из действующих ограничений, как в
notifications_0010: к ним добавляется `city_launch`, downgrade убирает его — так миграция не
теряет групп других веток. DROP → ADD … NOT VALID → VALIDATE после commit. Downgrade удаляет
выбор новой группы и её рассылки.

Ревизия: notifications_0012 (2026-10-14 09:00:00.000000+00:00)
Предыдущая: notifications_0011

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

import re
from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "notifications_0012"
down_revision: str | Sequence[str] | None = "notifications_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GROUP = "city_launch"
CHECKS = (
    ("notifications.preferences", "ck_preferences_event_group"),
    ("notifications.broadcasts", "ck_broadcasts_event_group"),
    ("notifications.broadcasts", "ck_broadcasts_opt_in_group"),
)


def _current(table: str, check: str) -> list[str]:
    """Группы действующего CHECK: значения в кавычках из его определения."""
    definition: str = (
        op.get_bind()
        .execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = :name AND conrelid = CAST(:table AS regclass)"
            ),
            {"name": check, "table": table},
        )
        .scalar_one()
    )
    return re.findall(r"'([^']+)'", definition)


def _groups(table: str, check: str, groups: Sequence[str]) -> None:
    values = ", ".join(f"'{group}'" for group in groups)
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {check}")
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {check} CHECK (event_group IN ({values})) NOT VALID"
    )


def _validate() -> None:
    with op.get_context().autocommit_block():
        for table, check in CHECKS:
            op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {check}")


def upgrade() -> None:
    for table, check in CHECKS:
        current = _current(table, check)
        if GROUP not in current:
            _groups(table, check, [*current, GROUP])
    _validate()


def downgrade() -> None:
    op.execute("DELETE FROM notifications.preferences WHERE event_group = 'city_launch'")
    op.execute("DELETE FROM notifications.broadcasts WHERE event_group = 'city_launch'")
    for table, check in CHECKS:
        _groups(table, check, [group for group in _current(table, check) if group != GROUP])
    _validate()
