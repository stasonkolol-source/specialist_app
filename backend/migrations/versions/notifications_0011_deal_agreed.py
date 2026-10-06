"""notifications_0011: тип `deal.agreed` — «Договорились» предложившей стороне (UX_GUIDANCE №14).

Вторая сторона подтвердила условия «Договориться» из чата (S53): предложившему — «Условия
подтверждены» и «Открыть чат»; раньше он видел это только строкой в чате. Длина varchar (30) не
меняется.

Список типов CHECK не переписывается целиком, а берётся из действующего ограничения, как в
notifications_0010: к нему добавляется `deal.agreed` (downgrade — убирает его). Так миграция не
теряет типы других веток. DROP → ADD … NOT VALID → VALIDATE после commit. Downgrade удаляет
строки нового типа.

Ревизия: notifications_0011 (2026-10-06 09:00:00.000000+00:00)
Предыдущая: notifications_0010

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

revision: str = "notifications_0011"
down_revision: str | Sequence[str] | None = "notifications_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "notifications.notifications"
CHECK = "ck_notifications_type"
ADDED = ("deal.agreed",)


def _current() -> list[str]:
    """Типы действующего CHECK: значения в кавычках из его определения."""
    definition: str = (
        op.get_bind()
        .execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = :name AND conrelid = CAST(:table AS regclass)"
            ),
            {"name": CHECK, "table": TABLE},
        )
        .scalar_one()
    )
    return re.findall(r"'([^']+)'", definition)


def _types(types: Sequence[str]) -> None:
    values = ", ".join(f"'{type_}'" for type_ in types)
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CHECK}")
    op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK} CHECK (type IN ({values})) NOT VALID")
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CHECK}")


def upgrade() -> None:
    current = _current()
    _types([*current, *(type_ for type_ in ADDED if type_ not in current)])


def downgrade() -> None:
    bind, added = op.get_bind(), {"types": list(ADDED)}
    bind.execute(
        text(
            "DELETE FROM notifications.deliveries WHERE notification_id IN"
            " (SELECT id FROM notifications.notifications WHERE type = ANY(:types))"
        ),
        added,
    )
    bind.execute(text("DELETE FROM notifications.notifications WHERE type = ANY(:types)"), added)
    _types([type_ for type_ in _current() if type_ not in ADDED])
