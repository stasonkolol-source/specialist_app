"""media_0003: видео — причина отказа `too_long` (ADR-0007, DEVELOPMENT_PLAN 2.2b).

Шаг 2.2b. Ролик длиннее минуты обработка отклоняет с `failure_reason = too_long`. Новый
CHECK — надмножество старого, длина varchar (23) не меняется. DROP → ADD … NOT VALID →
VALIDATE после commit, как в media_0002; повторный upgrade после сбоя проходит.

Ревизия: media_0003 (2026-09-29 21:30:00.000000+00:00)
Предыдущая: media_0002

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "media_0003"
down_revision: str | Sequence[str] | None = "media_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "media.assets"
CHECK = "ck_assets_failure_reason"
OLD = "'abandoned', 'mismatch', 'unsupported', 'too_many_pixels', 'unreadable'"
NEW = f"{OLD}, 'too_long'"


def _reasons(values: str) -> None:
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CHECK}")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK} CHECK (failure_reason IN ({values})) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CHECK}")


def upgrade() -> None:
    _reasons(NEW)


def downgrade() -> None:
    _reasons(OLD)
