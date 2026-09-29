"""media_0002: обработка и очистка файлов (ARCHITECTURE §10.3, §10.5, DEVELOPMENT_PLAN 2.2a).

Шаг 2.2a. Причины `rejected` (обработка не приняла файл) — в том же `failure_reason`:
`unsupported`, `too_many_pixels`, `unreadable`. Порядок: DROP CHECK → varchar(17) → (23)
(только метаданные: без CHECK нечего перепроверять) → ADD … NOT VALID коротко, VALIDATE —
после commit под SHARE UPDATE EXCLUSIVE (как в growth_0002). `attempts` — запуски
обработки (сбой не по вине файла повторяется до трёх раз); `hidden_at` — варианты
удалённого файла перенесены в private; `purged_at` — объекты удалённого файла отправлены на
удаление. Частичный индекс ищет удалённые, которые ждут скрытия или очистки.

Всё с IF [NOT] EXISTS: после сбоя посреди миграции (шаги в autocommit уже закоммичены)
повторный upgrade проходит; индекс, оставшийся INVALID после сбоя CONCURRENTLY,
пересоздаётся. Откат возвращает старый CHECK; строки с новыми причинами он не трогает —
VALIDATE тогда упадёт (ADR-0005: данные не теряем).

Ревизия: media_0002 (2026-09-29 20:00:00.000000+00:00)
Предыдущая: media_0001

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

revision: str = "media_0002"
down_revision: str | Sequence[str] | None = "media_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "media.assets"
CHECK = "ck_assets_failure_reason"
INDEX = "ix_assets_deleted_at"
OLD = "'abandoned', 'mismatch'"
NEW = "'abandoned', 'mismatch', 'unsupported', 'too_many_pixels', 'unreadable'"


def _reasons(values: str, length: int) -> None:
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CHECK}")
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN failure_reason TYPE varchar({length})")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK} CHECK (failure_reason IN ({values})) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CHECK}")


def upgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS attempts integer DEFAULT 0 NOT NULL")
    op.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS hidden_at timestamptz")
    op.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS purged_at timestamptz")
    _reasons(NEW, 23)
    with op.get_context().autocommit_block():
        invalid = op.get_bind().execute(
            sa.text(
                "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid"
                " JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE n.nspname = 'media' AND c.relname = :name AND NOT i.indisvalid"
            ),
            {"name": INDEX},
        )
        if invalid.first() is not None:  # прошлый CONCURRENTLY упал и оставил битый индекс
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS media.{INDEX}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON {TABLE} (deleted_at)"
            " WHERE status = 'deleted' AND purged_at IS NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS media.{INDEX}")
    _reasons(OLD, 17)
    for column in ("purged_at", "hidden_at", "attempts"):
        op.execute(f"ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {column}")
