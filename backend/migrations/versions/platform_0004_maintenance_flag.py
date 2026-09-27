"""platform_0004: публичный флаг техработ.

Шаг 1.5a (S49). Флаг `platform.maintenance` (выключен): включённый — API отвечает 503
`maintenance` на всё, кроме GET /client-config, а Mini App показывает экран техработ. Включает
его админка (или SQL) без деплоя. Флаг, уже созданный в админке, не перезаписывается; откат
удаляет только выключенный.

Ревизия: platform_0004 (2026-09-27 18:00:00.000000+00:00)
Предыдущая: growth_0001

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'platform_0004'
down_revision: str | Sequence[str] | None = 'growth_0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAINTENANCE = 'platform.maintenance'


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO platform.feature_flags (key, enabled, public, description)
        VALUES ('{MAINTENANCE}', false, true,
                'Техработы: API отвечает 503 maintenance, Mini App показывает экран S49')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM platform.feature_flags WHERE key = '{MAINTENANCE}' AND NOT enabled")
