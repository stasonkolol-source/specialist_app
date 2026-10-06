"""notifications_0010: типы `job.published`, `response.declined`, `deal.completed` (UX-аудит №11).

Клиенту — «Заявка опубликована» после ручной проверки; исполнителю — исходы в центре S42 без
бота: «Клиент отклонил отклик» и «Сделка выполнена». Длина varchar (30) не меняется.

Список типов CHECK не переписывается целиком, а берётся из действующего ограничения: к нему
добавляются три новых (downgrade — убирает их). Так миграция не зависит от порядка слияния с
другими, которые тоже добавляют типы (`deal.agreed` в notifications_0009), и не теряет их.
DROP → ADD … NOT VALID → VALIDATE после commit, как в notifications_0005. Downgrade удаляет строки
новых типов.

Ревизия: notifications_0010 (2026-10-05 21:40:00.000000+00:00)
Предыдущая: messaging_0003 (после notifications_0009 — та, что окажется раньше в цепочке)

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

revision: str = "notifications_0010"
down_revision: str | Sequence[str] | None = "messaging_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "notifications.notifications"
CHECK = "ck_notifications_type"
ADDED = ("job.published", "response.declined", "deal.completed")


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
    added = ", ".join(f"'{type_}'" for type_ in ADDED)
    op.execute(
        "DELETE FROM notifications.deliveries WHERE notification_id IN"
        f" (SELECT id FROM notifications.notifications WHERE type IN ({added}))"
    )
    op.execute(f"DELETE FROM notifications.notifications WHERE type IN ({added})")
    _types([type_ for type_ in _current() if type_ not in ADDED])
