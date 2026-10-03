"""media_0005: назначение `dispute` — фото-доказательства спора (DEVELOPMENT_PLAN 6.1c).

Файлы спора видят только стороны сделки и модератор: варианты — в приватном бакете, адреса —
presigned GET на 5 минут (domain/asset.py PUBLIC_PURPOSES). CHECK `purpose` — надмножество
старого, длина varchar (20) не меняется; DROP → ADD … NOT VALID → VALIDATE после commit, как в
notifications_0004. Откат возвращает старый список; файлы `dispute` откат не удаляет — VALIDATE
тогда упадёт (ADR-0005: данные не теряем).

Ревизия: media_0005 (2026-10-03 12:05:00.000000+00:00)
Предыдущая: deals_0003

Правила (DEVELOPMENT_PLAN 0.9, ADR-0005):
- имя ревизии — <модуль>_NNNN, файл — <модуль>_NNNN_<slug>.py;
- миграции идут под ролью migrator: lock_timeout = 3s задан роли, долгих блокировок нет;
- индексы на живых таблицах — CREATE INDEX CONCURRENTLY внутри op.get_context().autocommit_block();
- expand/contract: сначала добавить (nullable, новая колонка, двойная запись), удалять — отдельной
  миграцией после выкладки кода, который старое больше не читает.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "media_0005"
down_revision: str | Sequence[str] | None = "deals_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "media.assets"
CHECK = "ck_assets_purpose"
OLD = "'avatar', 'portfolio', 'job', 'message', 'review', 'verification'"
NEW = f"{OLD}, 'dispute'"


def _purposes(values: str) -> None:
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT {CHECK}")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CHECK} CHECK (purpose IN ({values})) NOT VALID"
    )
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CHECK}")


def upgrade() -> None:
    _purposes(NEW)


def downgrade() -> None:
    _purposes(OLD)
