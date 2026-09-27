"""platform_0003: действующие версии правил и политики в client-config.

Шаг 1.4a (ARCHITECTURE §8.5, §13.4). Галочка S02c записывает согласие с версиями из
`legal_versions`, поэтому они должны быть заданы до первого согласия. Версии — из
черновиков content/legal/ru (rules.md → terms, privacy.md → privacy): draft-1.
Значения, уже заданные в админке, не перезаписываются; откат убирает только свои.

Ревизия: platform_0003 (2026-09-27 12:40:00.000000+00:00)
Предыдущая: identity_0002

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'platform_0003'
down_revision: str | Sequence[str] | None = 'identity_0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEEDED = """'{"terms": "draft-1", "privacy": "draft-1"}'::jsonb"""


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE platform.client_config
        SET value = {SEEDED} || value, updated_at = now()
        WHERE key = 'legal_versions'
        """
    )


def downgrade() -> None:
    for document in ("terms", "privacy"):
        op.execute(
            f"""
            UPDATE platform.client_config
            SET value = value - '{document}', updated_at = now()
            WHERE key = 'legal_versions' AND value->>'{document}' = 'draft-1'
            """
        )
